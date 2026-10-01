"""Envoltorio mínimo de Chatterbox Multilingual con el finetune es-ES, con streaming por chunks (spike S1).

Basado en el código oficial de chatterbox-tts 0.1.7 (mtl_tts.py, T3, S3Gen) y en la demo oficial del finetune
(Space ResembleAI/Chatterbox-Multilingual-TTS-es-es, que vendoriza su propio código):
  - T3 = t3_es_es.safetensors con T3Config.multilingual() (vocabulario de texto 2454);
  - S3Gen = s3gen_v3.safetensors (10 pasos CFM, sin meanflow);
  - SIN AlignmentStreamAnalyzer (la demo del finetune tampoco lo usa; con él hay que sacar las atenciones en eager);
  - ve.pt, conds.pt y el tokenizador vienen del repo base ResembleAI/chatterbox.

El paquete oficial solo ofrece síntesis de frase completa (generate). Aquí se añade, sobre los mismos componentes,
un bucle de T3 que va soltando tokens por tandas y una decodificación S3Gen (flujo + vocoder) por chunk con contexto
a la izquierda y fundido cruzado, que es lo que hacen los forks de streaming de la comunidad. La marca de agua PerTh
solo se aplica en la ruta de frase completa (en streaming se omite; su coste se mide aparte).
"""

from __future__ import annotations

import time
import unicodedata
from pathlib import Path

import librosa
import numpy as np
import torch
import torch.nn.functional as F
from safetensors.torch import load_file
from tokenizers import Tokenizer
from transformers.generation.logits_process import (
    MinPLogitsWarper,
    RepetitionPenaltyLogitsProcessor,
    TopPLogitsWarper,
)

from chatterbox.models.s3gen import S3GEN_SR, S3Gen
from chatterbox.models.s3tokenizer import S3_SR
from chatterbox.models.t3 import T3
from chatterbox.models.t3.modules.cond_enc import T3Cond
from chatterbox.models.t3.modules.t3_config import T3Config
from chatterbox.models.voice_encoder import VoiceEncoder
from chatterbox.mtl_tts import Conditionals, punc_norm

SPACE = "[SPACE]"
SPEECH_VOCAB = 6561  # tokens de voz válidos: 0..6560 (6561 = inicio, 6562 = fin)
TOKEN_RATE = 25  # tokens de voz por segundo
TOKEN_SAMPLES = S3GEN_SR // TOKEN_RATE  # 960 muestras (40 ms) por token a 24 kHz
LOOKAHEAD = 3  # tokens de «mirada adelante» que necesita el codificador del flujo con finalize=False


class ChatterboxEs:
    ENC_COND_LEN = 6 * S3_SR
    DEC_COND_LEN = 10 * S3GEN_SR

    def __init__(self, ckpt_dir: Path, device: str = "cuda", text_norm: str = "space", t3_dtype: torch.dtype = torch.float32):
        ckpt_dir = Path(ckpt_dir)
        self.device = device
        self.sr = S3GEN_SR
        self.text_norm = text_norm  # "space" = como la demo del finetune; "pip" = minúsculas + NFKD como el paquete oficial
        self.load_report: dict = {}

        t0 = time.perf_counter()
        self.ve = VoiceEncoder()
        self.ve.load_state_dict(torch.load(ckpt_dir / "ve.pt", map_location="cpu", weights_only=True))
        self.ve.to(device).eval()

        self.t3 = T3(T3Config.multilingual())
        t3_state = load_file(str(ckpt_dir / "t3_es_es.safetensors"))
        if "model" in t3_state.keys():
            t3_state = t3_state["model"][0]
        self.t3.load_state_dict(t3_state)
        self.t3.to(device).eval()
        if t3_dtype != torch.float32:
            self.t3.to(t3_dtype)

        self.s3gen = S3Gen()
        res = self.s3gen.load_state_dict(load_file(str(ckpt_dir / "s3gen_v3.safetensors")), strict=False)
        self.load_report["s3gen_missing"] = list(res.missing_keys)
        self.load_report["s3gen_unexpected"] = list(res.unexpected_keys)
        self.s3gen.to(device).eval()

        self.tok = Tokenizer.from_file(str(ckpt_dir / "grapheme_mtl_merged_expanded_v1.json"))
        self.conds: Conditionals | None = None
        self._cond_emb: torch.Tensor | None = None
        self._cond_emb_key = None
        self.load_report["carga_s"] = time.perf_counter() - t0
        self.watermarker = None

    # ------------------------------------------------------------------ referencia (se cachea una vez)
    def prepare_conditionals(self, wav_path: Path, exaggeration: float = 0.5) -> None:
        """Igual que ChatterboxMultilingualTTS.prepare_conditionals (oficial)."""
        s3gen_ref_wav, _ = librosa.load(str(wav_path), sr=S3GEN_SR)
        ref_16k_wav = librosa.resample(s3gen_ref_wav, orig_sr=S3GEN_SR, target_sr=S3_SR)
        s3gen_ref_wav = s3gen_ref_wav[: self.DEC_COND_LEN]
        s3gen_ref_dict = self.s3gen.embed_ref(s3gen_ref_wav, S3GEN_SR, device=self.device)

        t3_cond_prompt_tokens = None
        if plen := self.t3.hp.speech_cond_prompt_len:
            s3_tokzr = self.s3gen.tokenizer
            t3_cond_prompt_tokens, _ = s3_tokzr.forward([ref_16k_wav[: self.ENC_COND_LEN]], max_len=plen)
            t3_cond_prompt_tokens = torch.atleast_2d(t3_cond_prompt_tokens).to(self.device)

        ve_embed = torch.from_numpy(self.ve.embeds_from_wavs([ref_16k_wav], sample_rate=S3_SR))
        ve_embed = ve_embed.mean(axis=0, keepdim=True).to(self.device)

        t3_cond = T3Cond(
            speaker_emb=ve_embed,
            cond_prompt_speech_tokens=t3_cond_prompt_tokens,
            emotion_adv=exaggeration * torch.ones(1, 1, 1),
        ).to(device=self.device)
        self.conds = Conditionals(t3_cond, s3gen_ref_dict)
        self._cond_emb = None
        self._gen_full = None

    def limit_decoder_prompt(self, seconds: float | None) -> None:
        """Recorta la referencia que ve el decodificador S3Gen (tokens + mel) a los primeros `seconds` s (None = completa).

        El flujo CFM procesa la referencia entera en cada chunk, así que su coste crece con la longitud de la referencia.
        Solo para medir el compromiso latencia/calidad: el T3 sigue viendo su condicionamiento normal.
        """
        if getattr(self, "_gen_full", None) is None:
            self._gen_full = dict(self.conds.gen)
        full = self._gen_full
        if seconds is None:
            self.conds.gen = dict(full)
            return
        n = min(int(seconds * TOKEN_RATE), int(full["prompt_token"].shape[1]))
        gen = dict(full)
        gen["prompt_token"] = full["prompt_token"][:, :n]
        gen["prompt_token_len"] = torch.tensor([n], dtype=full["prompt_token_len"].dtype, device=full["prompt_token"].device)
        gen["prompt_feat"] = full["prompt_feat"][:, : 2 * n]
        self.conds.gen = gen

    def _conditioning_embedding(self, exaggeration: float) -> torch.Tensor:
        """Embedding de condicionamiento de T3 (perceiver + voz + emoción), cacheado por (referencia, exageración)."""
        key = float(exaggeration)
        if self._cond_emb is None or self._cond_emb_key != key:
            c = self.conds.t3
            self.conds.t3 = T3Cond(
                speaker_emb=c.speaker_emb,
                cond_prompt_speech_tokens=c.cond_prompt_speech_tokens,
                emotion_adv=exaggeration * torch.ones(1, 1, 1),
            ).to(device=self.device)
            self._cond_emb = self.t3.prepare_conditioning(self.conds.t3)
            self._cond_emb_key = key
        return self._cond_emb

    # ------------------------------------------------------------------ texto
    def encode_text(self, text: str) -> torch.Tensor:
        text = punc_norm(text)
        if self.text_norm == "pip":
            text = unicodedata.normalize("NFKD", text.lower())
        ids = self.tok.encode(("[es]" + text).replace(" ", SPACE)).ids
        return torch.IntTensor(ids).unsqueeze(0)

    # ------------------------------------------------------------------ T3: tokens de voz
    @torch.inference_mode()
    def speech_tokens(self, text: str, *, cfg_weight=0.5, exaggeration=0.5, temperature=0.8, repetition_penalty=1.2, min_p=0.05, top_p=1.0, max_new_tokens=500, trace: dict | None = None):
        """Generador de tokens de voz (uno a uno), con el mismo muestreo que T3.inference oficial. Termina al emitir EOS.

        Con trace={} se guardan marcas de tiempo (prefill terminado y hora de cada token) para el desglose de la latencia.
        """
        t3 = self.t3
        hp = t3.hp
        dev = self.device
        use_cfg = cfg_weight > 0.0

        text_tokens = self.encode_text(text).to(dev)
        text_tokens = F.pad(text_tokens, (1, 0), value=hp.start_text_token)
        text_tokens = F.pad(text_tokens, (0, 1), value=hp.stop_text_token)
        text_tokens = text_tokens.to(torch.long)
        if use_cfg:
            text_tokens = torch.cat([text_tokens, text_tokens], dim=0)  # 2 secuencias: condicionada y sin condición

        cond_emb = self._conditioning_embedding(exaggeration)
        text_emb = t3.text_emb(text_tokens)
        if use_cfg:
            text_emb[1].zero_()  # CFG: la secuencia sin condición no ve el texto
        text_emb = text_emb + t3.text_pos_emb(text_tokens)
        start = hp.start_speech_token * torch.ones_like(text_tokens[:, :1])
        speech_emb = t3.speech_emb(start) + t3.speech_pos_emb(start)
        bos = torch.tensor([[hp.start_speech_token]], dtype=torch.long, device=dev)
        bos_embed = t3.speech_emb(bos) + t3.speech_pos_emb.get_fixed_embedding(0)
        B = text_tokens.size(0)
        if B == 2:
            bos_embed = torch.cat([bos_embed, bos_embed])
        ce = cond_emb.expand(B, -1, -1)
        inputs_embeds = torch.cat([torch.cat([ce, text_emb, speech_emb], dim=1), bos_embed], dim=1)

        generated = bos.clone()
        rep = RepetitionPenaltyLogitsProcessor(penalty=float(repetition_penalty))
        minp = MinPLogitsWarper(min_p=min_p)
        topp = TopPLogitsWarper(top_p=top_p)

        out = t3.tfmr(inputs_embeds=inputs_embeds, past_key_values=None, use_cache=True)
        past = out.past_key_values
        hidden = out.last_hidden_state
        if trace is not None:
            torch.cuda.synchronize()
            trace["t_prefill_done"] = time.perf_counter()
            trace["prefill_tokens"] = int(inputs_embeds.shape[1])
            trace["t_tokens"] = []
        for i in range(max_new_tokens):
            logits = t3.speech_head(hidden[:, -1:, :])[:, -1, :]
            if use_cfg:
                cond, uncond = logits[0:1], logits[1:2]
                logits = cond + cfg_weight * (cond - uncond)
            logits = rep(generated[:1], logits)
            if temperature != 1.0:
                logits = logits / temperature
            logits = minp(generated[:1], logits)
            logits = topp(generated[:1], logits)
            nxt = torch.multinomial(torch.softmax(logits, dim=-1), num_samples=1)  # (1, 1)
            generated = torch.cat([generated, nxt], dim=1)
            tok = int(nxt.item())
            if trace is not None:
                trace["t_tokens"].append(time.perf_counter())
            if tok == hp.stop_speech_token:
                return
            yield tok
            emb = t3.speech_emb(nxt) + t3.speech_pos_emb.get_fixed_embedding(i + 1)
            if B == 2:
                emb = torch.cat([emb, emb])
            out = t3.tfmr(inputs_embeds=emb, past_key_values=past, use_cache=True)
            past = out.past_key_values
            hidden = out.last_hidden_state

    # ------------------------------------------------------------------ S3Gen: tokens -> audio
    @torch.inference_mode()
    def _mels(self, tokens: list[int], finalize: bool, n_timesteps: int | None = None) -> torch.Tensor:
        """Tokens -> mel con el flujo de S3Gen.

        Es CausalMaskedDiffWithXvec.inference de chatterbox-tts 0.1.7 con UNA corrección: con finalize=False el paquete
        recorta h (los 3 últimos tokens) pero calcula la máscara con la longitud sin recortar y la ejecución falla
        («expanded size of the tensor (420) must match the existing size (426)»). Con batch 1 no hay relleno, así que
        la máscara correcta es todo unos.
        """
        from chatterbox.models.s3gen.utils.mask import make_pad_mask

        flow = self.s3gen.flow
        ref = self.conds.gen
        tok = torch.tensor([tokens], dtype=torch.long, device=self.device)
        emb = flow.spk_embed_affine_layer(F.normalize(torch.atleast_2d(ref["embedding"]), dim=1))
        prompt_feat = ref["prompt_feat"]
        token = torch.cat([ref["prompt_token"], tok], dim=1)
        token_len = ref["prompt_token_len"] + tok.size(1)
        mask = (~make_pad_mask(token_len)).unsqueeze(-1).to(emb)
        token = flow.input_embedding(token.long()) * mask
        h, _ = flow.encoder(token, token_len)
        if not finalize:
            h = h[:, : -flow.pre_lookahead_len * flow.token_mel_ratio]
        mel_len1 = prompt_feat.shape[1]
        mel_len2 = h.shape[1] - mel_len1
        h = flow.encoder_proj(h)
        conds = torch.zeros([1, mel_len1 + mel_len2, flow.output_size], device=token.device).to(h.dtype)
        conds[:, :mel_len1] = prompt_feat
        conds = conds.transpose(1, 2)
        mask = torch.ones([1, 1, mel_len1 + mel_len2], device=token.device, dtype=h.dtype)
        feat, _ = flow.decoder(mu=h.transpose(1, 2).contiguous(), mask=mask, spks=emb, cond=conds, n_timesteps=n_timesteps or 10, noised_mels=None, meanflow=False)
        return feat[:, :, mel_len1:]

    @torch.inference_mode()
    def _decode(self, tokens: list[int], finalize: bool, n_cfm_timesteps: int | None = None) -> np.ndarray:
        """Flujo (CFM) + vocoder HiFT sobre una ventana de tokens. Con finalize=False se descartan los últimos 3 tokens."""
        mels = self._mels(tokens, finalize, n_cfm_timesteps)
        wav, _ = self.s3gen.hift_inference(mels.to(dtype=self.s3gen.dtype), None)
        wav[:, : len(self.s3gen.trim_fade)] *= self.s3gen.trim_fade
        return wav.squeeze(0).float().cpu().numpy()

    # ------------------------------------------------------------------ frase completa (ruta oficial)
    @torch.inference_mode()
    def synthesize(self, text: str, *, watermark: bool = False, seed: int | None = None, **gen) -> np.ndarray:
        if seed is not None:
            torch.manual_seed(seed)
        toks = [t for t in self.speech_tokens(text, **gen) if t < SPEECH_VOCAB]
        wav = self._decode(toks, finalize=True)
        # La demo oficial descarta el audio del último token (~40 ms de ruido justo antes del EOS).
        wav = wav[: max(1, len(toks) - 1) * TOKEN_SAMPLES]
        if watermark:
            wav = self.watermark(wav)
        return wav

    def watermark(self, wav: np.ndarray) -> np.ndarray:
        if self.watermarker is None:
            import perth

            self.watermarker = perth.PerthImplicitWatermarker()
        return self.watermarker.apply_watermark(wav, sample_rate=self.sr)

    # ------------------------------------------------------------------ streaming por chunks
    @torch.inference_mode()
    def stream(self, text: str, *, first_chunk_tokens: int = 10, chunk_tokens: int = 25, ctx_tokens: int = 10, xfade_ms: float = 10.0, seed: int | None = None, n_cfm_timesteps: int | None = None, trace: dict | None = None, **gen):
        """Genera audio por chunks. Cada elemento: {'audio': np.float32, 'n_tokens': total de tokens hasta ahora, 'final': bool}.

        El primer chunk sale cuando hay first_chunk_tokens + 3 tokens (los 3 últimos son la mirada adelante del flujo).
        Con trace={} se rellenan marcas de tiempo (t0, prefill, cada token, cada decodificación S3Gen) para el desglose.
        """
        if seed is not None:
            torch.manual_seed(seed)
        if trace is not None:
            trace["t0"] = time.perf_counter()
            trace["emit"] = []
        xf = int(self.sr * xfade_ms / 1000)
        fade_in = np.linspace(0.0, 1.0, xf, dtype=np.float32) if xf else None
        toks: list[int] = []
        emitted = 0  # tokens cuyo audio ya se ha emitido (o está en la cola de fundido)
        held: np.ndarray | None = None  # últimas xf muestras del chunk anterior, pendientes de fundir
        next_emit = first_chunk_tokens + LOOKAHEAD

        def emit(final: bool):
            nonlocal emitted, held
            ctx_start = max(0, emitted - ctx_tokens)
            win = toks[ctx_start:]
            t_a = time.perf_counter()
            wav = self._decode(win, finalize=final, n_cfm_timesteps=n_cfm_timesteps)
            if trace is not None:
                trace["emit"].append((t_a, time.perf_counter(), len(win)))
            end_tok = len(toks) - (1 if final else LOOKAHEAD)  # en el final se descarta el último token (ruido antes del EOS)
            end_tok = max(end_tok, emitted)
            a0 = (emitted - ctx_start) * TOKEN_SAMPLES
            a1 = (end_tok - ctx_start) * TOKEN_SAMPLES
            if xf and held is not None:
                seg = wav[a0 - xf : a1].copy()
                seg[:xf] = held * (1.0 - fade_in) + seg[:xf] * fade_in
            else:
                seg = wav[a0:a1].copy()
            if xf and not final:
                held = seg[-xf:].copy()
                out = seg[:-xf]
            else:
                held = None
                out = seg
            emitted = end_tok
            return out

        for tok in self.speech_tokens(text, trace=trace, **gen):
            if tok >= SPEECH_VOCAB:
                continue
            toks.append(tok)
            if len(toks) >= next_emit:
                yield {"audio": emit(final=False), "n_tokens": len(toks), "final": False}
                next_emit = len(toks) + chunk_tokens
        if len(toks) > 1:
            yield {"audio": emit(final=True), "n_tokens": len(toks), "final": True}
