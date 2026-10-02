"""Tests de ``mt/hymt2.py``: ``HyMt2Translator`` con un ``llama-server`` falso (``httpx.MockTransport``).

Sin GPU ni modelos. El texto del *prompt* se compara con el literal de S2 (``spikes/traduccion/README.md``,
«Prompt final»), no con las constantes del módulo: si alguien las toca, estos tests avisan.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
import pytest

from instanttraductor.contracts import (
    EngineError,
    GlossaryEntry,
    SourceLanguage,
    TranslationMode,
    TranslationRequest,
    Translator,
)
from instanttraductor.mt import hymt2
from instanttraductor.mt.hymt2 import (
    HyMt2Translator,
    build_concise_messages,
    build_normal_messages,
    concise_word_budget,
    count_characters,
    count_words,
    load_base_glossary,
    max_tokens_for,
    rejection_reason,
    select_glossary,
)
from instanttraductor.mt.llama_server import find_free_port
from instanttraductor.mt.selection import MtModel
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.test_translation_contract import SENTENCES, TranslatorContract, make_request

BASE_URL = "http://127.0.0.1:8080"

# --- Literales de S2 (spikes/traduccion/README.md y resultados/metricas.json, «example») ---
S2_SYSTEM = (
    "Translate every user message into Spanish. The translation style must strictly conform to "
    '[natural and concise Spanish from Spain (peninsular); use "vosotros" for the informal plural "you"]. '
    "ONLY output the translated result without any additional explanation."
)
S2_WRAPPER = (
    "Translate the following text into Spanish. Note that you must ONLY output the translated result "
    "without any additional explanation:\n\n"
)
S2_TERMINOLOGY_HEAD = "参考下面的翻译：\n"
S2_TERMINOLOGY_TAIL = "\n将以下文本翻译为西班牙语，注意只需要输出翻译后的结果，不要额外解释：\n\n"
S2_FIRST_SHOT = (
    "Are you guys hungry? I can make some mashed potatoes.",
    "¿Tenéis hambre? Puedo hacer un puré de patatas.",
)
S2_LAST_SHOT = ("We'll take the subway to the stadium.", "Cogeremos el metro hasta el estadio.")
CONCISE_PREFIX = (
    "Please translate the following text into Spanish. Note that the translation style must strictly "
    "conform to [telegraphic Spanish from Spain, like a news headline: drop filler words, at most "
)
#: Lo que sigue al tope de palabras: la cláusula de estilo con el registro informal (T018, R8).
CONCISE_STYLE_CLAUSE = (
    '; informal register: several listeners = "vosotros" (estáis, tenéis, venid), one listener = "tú"]:'
)


# ---------------------------------------------------------------------------
# llama-server falso
# ---------------------------------------------------------------------------
def chat_response(text: str, finish_reason: str | None = "stop") -> httpx.Response:
    """Respuesta de ``/v1/chat/completions`` con ``text`` como contenido."""
    message = {"role": "assistant", "content": text}
    return httpx.Response(
        200, json={"choices": [{"index": 0, "message": message, "finish_reason": finish_reason}]}
    )


def source_of(body: dict[str, Any]) -> str:
    """El original que se pide traducir: el texto tras la instrucción del último turno de usuario."""
    return body["messages"][-1]["content"].rsplit("\n\n", 1)[-1]


KNOWN = {
    "hello there my friend": "hola, amigo mío",
    "I think we should leave before it gets dark": "creo que deberíamos irnos antes de que oscurezca",
    "okay": "vale",
    "put the juice in the fridge": "pon el zumo en la nevera",
}


def default_responder(body: dict[str, Any]) -> httpx.Response:
    source = source_of(body)
    if source == "refuse me":
        return chat_response("你好")  # una salida que los filtros descartan
    return chat_response(KNOWN.get(source, f"ES: {source}"))


class FakeChatServer:
    """``llama-server`` falso: guarda los cuerpos recibidos y responde con ``responder``."""

    def __init__(self, responder: Callable[[dict[str, Any]], httpx.Response] = default_responder) -> None:
        self.responder = responder
        self.bodies: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        body = json.loads(request.content)
        self.bodies.append(body)
        return self.responder(body)

    @property
    def messages(self) -> list[dict[str, str]]:
        return self.bodies[-1]["messages"]


def make_translator(
    server: FakeChatServer | None = None,
    kind: MtModel | str = MtModel.HY_MT2_7B,
    *,
    clock: ManualClock | None = None,
) -> tuple[HyMt2Translator, FakeChatServer]:
    server = server or FakeChatServer()
    translator = HyMt2Translator(BASE_URL, kind, clock=clock or ManualClock(), transport=server.transport)
    return translator, server


@pytest.fixture
def no_base_glossary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin glosario base: los tests del *prompt* exacto no dependen del contenido del TOML."""
    monkeypatch.setattr(hymt2, "_base_matchers", lambda: ())


# ---------------------------------------------------------------------------
# Contrato de Translator
# ---------------------------------------------------------------------------
def _contract_requests() -> list[TranslationRequest]:
    normal = [make_request(unit_id, text) for unit_id, text in enumerate(SENTENCES, start=1)]
    return [*normal, make_request(99, "refuse me")]  # la última provoca un rechazo


class TestHyMt2Translator7b(TranslatorContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], Translator]:
        return lambda: make_translator(kind=MtModel.HY_MT2_7B)[0]

    @pytest.fixture
    def requests(self) -> list[TranslationRequest]:
        return _contract_requests()

    def test_it_supports_concise_and_the_rejection_branch_is_exercised(self) -> None:
        translator = make_translator(kind=MtModel.HY_MT2_7B)[0]
        assert translator.supports_concise is True
        rejected = translator.translate(make_request(99, "refuse me"))
        assert rejected.rejected is True
        assert rejected.text == ""


class TestHyMt2Translator1_8b(TranslatorContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], Translator]:
        return lambda: make_translator(kind=MtModel.HY_MT2_1_8B)[0]

    @pytest.fixture
    def requests(self) -> list[TranslationRequest]:
        return _contract_requests()

    def test_it_does_not_support_concise(self) -> None:
        assert make_translator(kind=MtModel.HY_MT2_1_8B)[0].supports_concise is False


# ---------------------------------------------------------------------------
# Identidad
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "name", "concise"),
    [
        (MtModel.HY_MT2_7B, "hy-mt2-7b-q4", True),
        ("7b", "hy-mt2-7b-q4", True),
        ("hy-mt2-7b-q4", "hy-mt2-7b-q4", True),
        (MtModel.HY_MT2_1_8B, "hy-mt2-1.8b-q8", False),
        ("1.8b", "hy-mt2-1.8b-q8", False),
    ],
)
def test_name_and_concise_support_follow_the_model(kind: MtModel | str, name: str, concise: bool) -> None:
    translator = make_translator(kind=kind)[0]
    assert translator.name == name
    assert translator.supports_concise is concise


def test_an_unknown_model_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="desconocido"):
        HyMt2Translator(BASE_URL, "13b")


# ---------------------------------------------------------------------------
# Petición HTTP
# ---------------------------------------------------------------------------
def test_request_goes_to_chat_completions_with_the_sampling_of_s2() -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "hello there my friend"))

    assert server.paths == ["/v1/chat/completions"]
    body = server.bodies[0]
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.6
    assert body["top_k"] == 20
    assert body["repeat_penalty"] == 1.05
    assert body["seed"] == 42
    assert body["cache_prompt"] is True
    assert body["stream"] is False
    assert body["max_tokens"] == 64


@pytest.mark.parametrize(
    ("n_words", "expected"),
    [(1, 64), (5, 64), (16, 64), (17, 68), (30, 120), (127, 508), (128, 512), (500, 512)],
)
def test_max_tokens_is_four_per_word_between_64_and_512(n_words: int, expected: int) -> None:
    assert max_tokens_for(" ".join(["word"] * n_words)) == expected


def test_words_count_contractions_as_one() -> None:
    assert count_words("I can't believe you're here, man.") == 6
    assert count_words("") == 0
    assert count_words("... ?!") == 0


# ---------------------------------------------------------------------------
# Prompt NORMAL (el final de S2)
# ---------------------------------------------------------------------------
def test_normal_prompt_is_system_then_12_examples_then_context_then_the_turn(no_base_glossary: None) -> None:
    translator, server = make_translator()
    context = (("Hi.", "Hola."), ("How are you?", "¿Cómo estás?"))

    translator.translate(make_request(7, "Where were you last night?", context=context))

    messages = server.messages
    assert len(messages) == 1 + 2 * 12 + 2 * 2 + 1
    assert messages[0] == {"role": "system", "content": S2_SYSTEM}
    # Los 12 ejemplos fijos, cada uno como turno de usuario envuelto + respuesta del asistente.
    assert messages[1] == {"role": "user", "content": S2_WRAPPER + S2_FIRST_SHOT[0]}
    assert messages[2] == {"role": "assistant", "content": S2_FIRST_SHOT[1]}
    assert messages[23] == {"role": "user", "content": S2_WRAPPER + S2_LAST_SHOT[0]}
    assert messages[24] == {"role": "assistant", "content": S2_LAST_SHOT[1]}
    # El contexto, del más antiguo al más reciente, también como turnos de chat.
    assert messages[25] == {"role": "user", "content": S2_WRAPPER + "Hi."}
    assert messages[26] == {"role": "assistant", "content": "Hola."}
    assert messages[27] == {"role": "user", "content": S2_WRAPPER + "How are you?"}
    assert messages[28] == {"role": "assistant", "content": "¿Cómo estás?"}
    # Y el turno final, envuelto en la instrucción, sin glosario.
    assert messages[29] == {"role": "user", "content": S2_WRAPPER + "Where were you last night?"}
    assert [m["role"] for m in messages[1:-1]] == ["user", "assistant"] * 14


def test_without_context_the_prompt_has_only_the_fixed_examples(no_base_glossary: None) -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "Where were you last night?"))

    assert len(server.messages) == 1 + 2 * 12 + 1


def test_the_prefix_up_to_the_context_is_identical_between_requests(no_base_glossary: None) -> None:
    """Es lo que ``cache_prompt`` reutiliza: sistema y 12 ejemplos no cambian de una frase a otra."""
    translator, server = make_translator()

    translator.translate(make_request(1, "hello there my friend"))
    translator.translate(make_request(2, "okay", context=(("hello there my friend", "hola"),)))

    first, second = server.bodies[0]["messages"], server.bodies[1]["messages"]
    assert first[:-1] == second[:25]


def test_context_pairs_with_empty_text_are_skipped(no_base_glossary: None) -> None:
    translator, server = make_translator()
    context = (("Hi.", ""), ("", "Hola."), ("  ", " "), ("How are you?", "¿Cómo estás?"))

    translator.translate(make_request(1, "okay", context=context))

    assert len(server.messages) == 1 + 2 * 12 + 2 + 1
    assert server.messages[-2] == {"role": "assistant", "content": "¿Cómo estás?"}


def test_the_source_is_stripped_and_inserted_literally(no_base_glossary: None) -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "  put {this} on the {table}\n"))

    assert server.messages[-1]["content"] == S2_WRAPPER + "put {this} on the {table}"


# ---------------------------------------------------------------------------
# Glosario: el del usuario más el base filtrado por la frase
# ---------------------------------------------------------------------------
def terminology_rows(message: str) -> list[str]:
    """Filas «origen 翻译成 destino» de un turno con la plantilla Terminology; comprueba el resto."""
    assert message.startswith(S2_TERMINOLOGY_HEAD)
    head_and_rows, source = message.split(S2_TERMINOLOGY_TAIL, 1)
    assert source  # el original va al final
    return head_and_rows.removeprefix(S2_TERMINOLOGY_HEAD).split("\n")


def test_user_glossary_uses_the_terminology_template_in_chinese(no_base_glossary: None) -> None:
    translator, server = make_translator()
    glossary = (GlossaryEntry("Ember Court", "Corte de Ascuas"), GlossaryEntry("Glassreach", "Cristalcanto"))
    text = "The Ember Court has closed the gates of Glassreach, and nobody is allowed in or out."

    translator.translate(make_request(1, text, glossary=glossary))

    assert server.messages[-1] == {
        "role": "user",
        "content": (
            "参考下面的翻译：\nEmber Court 翻译成 Corte de Ascuas\nGlassreach 翻译成 Cristalcanto\n"
            "将以下文本翻译为西班牙语，注意只需要输出翻译后的结果，不要额外解释：\n\n" + text
        ),
    }
    # Los turnos anteriores (ejemplos) siguen siendo los envueltos en inglés.
    assert all("参考下面的翻译" not in m["content"] for m in server.messages[:-1])


def test_without_any_glossary_the_last_turn_is_the_plain_wrapper(no_base_glossary: None) -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "okay"))

    assert "参考" not in json.dumps(server.messages, ensure_ascii=False)


def test_the_base_glossary_is_filtered_by_the_sentence() -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "put the juice in the fridge"))

    rows = terminology_rows(server.messages[-1]["content"])
    assert "juice 翻译成 zumo" in rows
    assert "fridge 翻译成 nevera" in rows
    assert len(rows) == len(select_glossary("put the juice in the fridge"))


def test_a_sentence_without_base_terms_gets_no_terminology_block() -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "I think we should leave before it gets dark"))

    assert server.messages[-1]["content"] == S2_WRAPPER + "I think we should leave before it gets dark"


def test_user_entries_come_first_and_all_of_them_are_included() -> None:
    translator, server = make_translator()
    glossary = (GlossaryEntry("Hollowmere", "Yermomar"), GlossaryEntry("Kaelith Vorne", "Kaelith Vorne"))

    translator.translate(make_request(1, "put the juice in the fridge", glossary=glossary))

    rows = terminology_rows(server.messages[-1]["content"])
    assert rows[:2] == [
        "Hollowmere 翻译成 Yermomar",
        "Kaelith Vorne 翻译成 Kaelith Vorne",
    ]  # aunque no aparezcan
    assert "juice 翻译成 zumo" in rows[2:]


def test_a_user_term_overrides_the_same_base_term() -> None:
    entries = select_glossary("my car", (GlossaryEntry("Car", "carro"),))

    assert entries == (GlossaryEntry("Car", "carro"),)  # no se añade «car → coche» del base


def test_blank_and_repeated_user_entries_are_ignored() -> None:
    user = (
        GlossaryEntry("", "x"),
        GlossaryEntry("x", ""),
        GlossaryEntry("  ", "  "),
        GlossaryEntry("Quill", "Quill"),
        GlossaryEntry("quill", "otra"),
    )
    assert select_glossary("nothing here", user) == (GlossaryEntry("Quill", "Quill"),)


@pytest.mark.parametrize(
    ("sentence", "term"),
    [
        ("Put it in the FRIDGE.", "fridge"),  # sin distinguir mayúsculas
        ("The fridge's door is open.", "fridge"),  # con apóstrofo
        ("There are two cars outside.", "car"),  # plural en «s»
        ("Popcorn?", "popcorn"),
        ("Okay, okay.", "okay"),
    ],
)
def test_base_terms_match_as_whole_words_with_an_optional_plural(sentence: str, term: str) -> None:
    assert term in [entry.source for entry in select_glossary(sentence)]


@pytest.mark.parametrize(
    ("sentence", "term"),
    [
        ("Look at that carpet and the cartoon.", "car"),
        ("The juicer is broken.", "juice"),
        ("She cares a lot.", "car"),
        ("A smart fridgerator.", "fridge"),
    ],
)
def test_base_terms_do_not_match_inside_other_words(sentence: str, term: str) -> None:
    assert term not in [entry.source for entry in select_glossary(sentence)]


def test_concise_mode_does_not_send_the_glossary() -> None:
    translator, server = make_translator()

    translator.translate(
        make_request(
            1,
            "put the juice in the fridge",
            TranslationMode.CONCISE,
            glossary=(GlossaryEntry("Hollowmere", "Yermomar"),),
        )
    )

    assert "参考" not in server.messages[-1]["content"]


# ---------------------------------------------------------------------------
# Modo CONCISE
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("n_words", "budget"),
    [(1, 1), (2, 2), (3, 2), (5, 3), (9, 6), (10, 6), (20, 12), (100, 60), (200, 120)],
)
def test_the_concise_budget_is_ceil_of_0_6_times_the_words(n_words: int, budget: int) -> None:
    assert concise_word_budget(" ".join(["word"] * n_words)) == budget


def test_the_concise_budget_has_a_floor_of_one_word() -> None:
    assert concise_word_budget("") == 1
    assert concise_word_budget("... ?!") == 1


def test_concise_mode_is_a_single_style_message_with_the_word_budget() -> None:
    translator, server = make_translator()
    text = "I think we should leave before it gets dark"  # 9 palabras -> N = 6

    result = translator.translate(make_request(1, text, TranslationMode.CONCISE))

    assert result.mode is TranslationMode.CONCISE
    expected = CONCISE_PREFIX + "6 words" + CONCISE_STYLE_CLAUSE + "\n\n" + text
    assert server.messages == [{"role": "user", "content": expected}]
    assert server.bodies[0]["cache_prompt"] is True


def test_concise_mode_ignores_context_and_the_fixed_examples() -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "okay", TranslationMode.CONCISE, context=(("Hi.", "Hola."),)))

    assert len(server.messages) == 1
    assert "Hola." not in server.messages[0]["content"]


def test_build_concise_messages_accepts_an_explicit_budget() -> None:
    assert build_concise_messages("one two three", 2) == [
        {"role": "user", "content": CONCISE_PREFIX + "2 words" + CONCISE_STYLE_CLAUSE + "\n\none two three"}
    ]


def test_the_1_8b_translates_normally_when_asked_to_summarise() -> None:
    translator, server = make_translator(kind=MtModel.HY_MT2_1_8B)

    result = translator.translate(make_request(3, "hello there my friend", TranslationMode.CONCISE))

    assert result.mode is TranslationMode.NORMAL  # lo que se hizo de verdad
    assert len(server.messages) > 20  # el prompt normal, con los 12 ejemplos
    assert server.messages[-1]["content"].endswith("hello there my friend")
    assert "telegraphic" not in json.dumps(server.messages)


def test_normal_mode_is_never_concise() -> None:
    translator, server = make_translator()

    result = translator.translate(make_request(1, "hello there my friend"))

    assert result.mode is TranslationMode.NORMAL
    assert "telegraphic" not in json.dumps(server.messages)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------
def test_the_result_carries_the_unit_the_text_and_the_session_clock() -> None:
    clock = ManualClock(10.0)

    def slow_server(body: dict[str, Any]) -> httpx.Response:
        clock.advance(0.25)  # la traducción «tarda» 0,25 s de reloj de sesión
        return chat_response("  hola, amigo mío \n")

    translator, _ = make_translator(FakeChatServer(slow_server), clock=clock)

    result = translator.translate(make_request(42, "hello there my friend"))

    assert result.unit_id == 42
    assert result.text == "hola, amigo mío"  # sin espacios sobrantes
    assert result.rejected is False
    assert result.started_at == 10.0
    assert result.finished_at == 10.25


def test_a_rejected_result_has_empty_text_and_keeps_unit_and_mode() -> None:
    translator, _ = make_translator()

    result = translator.translate(make_request(5, "refuse me", TranslationMode.CONCISE))

    assert result.rejected is True
    assert result.text == ""
    assert result.unit_id == 5
    assert result.mode is TranslationMode.CONCISE


def test_a_rejection_is_logged_with_its_reason(caplog: pytest.LogCaptureFixture) -> None:
    translator, _ = make_translator()

    with caplog.at_level("WARNING", logger="instanttraductor.mt.hymt2"):
        translator.translate(make_request(5, "refuse me"))

    assert "idioma" in caplog.text
    assert "unidad 5" in caplog.text


def test_a_unit_with_blank_text_is_rejected_without_calling_the_server() -> None:
    translator, server = make_translator()

    result = translator.translate(make_request(1, "   "))

    assert result.rejected is True
    assert result.text == ""
    assert server.bodies == []


def test_a_truncated_answer_is_rejected() -> None:
    translator, _ = make_translator(FakeChatServer(lambda body: chat_response("hola amigo", "length")))

    result = translator.translate(make_request(1, "hello there my friend"))

    assert result.rejected is True


def test_without_a_clock_it_uses_its_own_session_clock() -> None:
    server = FakeChatServer()
    translator = HyMt2Translator(BASE_URL, "7b", transport=server.transport)

    result = translator.translate(make_request(1, "okay"))

    assert 0.0 <= result.started_at <= result.finished_at


# ---------------------------------------------------------------------------
# Filtros de salida
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("source", "output", "reason"),
    [
        # vacía
        ("hello there", "", "vacía"),
        ("hello there", "  \n\t ", "vacía"),
        # sin letras latinas, o con otras escrituras
        ("hello there my friend", "你好，我的朋友", "idioma"),
        ("hello there my friend", "こんにちは", "idioma"),
        ("hello there my friend", "안녕하세요", "idioma"),
        ("hello there my friend", "Привет, друг", "idioma"),
        ("hello there my friend", "مرحبا يا صديقي", "idioma"),
        ("hello there my friend", "...", "idioma"),
        ("hello there my friend", "1234 !?", "idioma"),
        ("hello there my friend", "hola amigo 你好", "idioma"),
        # más de 3 veces el original (en caracteres) o cortada
        ("Okay.", "Vale, vale, vale, vale, vale, vale, vale.", "longitud"),
        ("abcd", "x" * 13, "longitud"),
        # eco del prompt y muletillas
        ("Okay, I will go with you.", "Translate the following text into Spanish.", "eco del prompt"),
        ("Okay, I will go with you.", "Only output the translated result.", "eco del prompt"),
        ("Okay, I will go with you.", "[Texto de origen] Vale, iré contigo.", "eco del prompt"),
        ("Okay, I will go with you.", "[Source Text]\nVale, iré contigo.", "eco del prompt"),
        ("Okay, I will go with you.", "[Información de fondo] Conversación hasta ahora", "eco del prompt"),
        ("Okay, I will go with you.", "Spanish: Vale, iré contigo.", "eco del prompt"),
        ("Okay, I will go with you.", "Aquí tienes la traducción: Vale, iré contigo.", "eco del prompt"),
        ("Okay, I will go with you.", "Translation: Vale, iré contigo.", "eco del prompt"),
        ("Okay, I will go with you.", "Here is the translation: vale.", "eco del prompt"),
        ("Okay, I will go with you.", "Nota: no he cambiado nada.", "eco del prompt"),
        (
            "Okay, I will go with you.",
            "Traduce el siguiente texto al español, sin ninguna explicación adicional.",
            "eco del prompt",
        ),
    ],
)
def test_outputs_that_are_not_a_translation_are_rejected(source: str, output: str, reason: str) -> None:
    assert rejection_reason(source, output) == reason


def test_exactly_three_times_the_original_is_still_accepted() -> None:
    assert rejection_reason("abcd", "x" * 12) is None


def test_finish_reason_length_is_a_length_rejection() -> None:
    assert rejection_reason("hello there my friend", "hola amigo", finish_reason="length") == "longitud"
    assert rejection_reason("hello there my friend", "hola amigo", finish_reason="stop") is None


@pytest.mark.parametrize(
    ("source", "output"),
    [
        ("Okay.", "Vale."),
        ("Hmm.", "Mmm."),
        ("Wow!", "¡Guau!"),
        ("Sure, I can help.", "Claro, puedo ayudar."),  # «Claro, ...» no es una muletilla
        ("Here's your coffee.", "Aquí tienes tu café."),  # «Aquí tienes» tampoco
        ("Of course.", "Por supuesto."),
        ("Translate this sentence into French, please.", "Traduce esta frase al francés, por favor."),
        ("Translate the following text into French.", "Traduce el siguiente texto al francés."),
        ("Summarize the plot of the movie in one sentence.", "Resume la trama de la película en una frase."),
        ("The note says: don't go.", "La nota dice: no vayas."),
        ("Nobody knows the translation of that word.", "Nadie sabe la traducción de esa palabra."),
        ("Where is the source text?", "¿Dónde está el texto de origen?"),
        ("Zephyrine Quill swore.", "Zefirina Quill juró."),
        ("It costs 15 dollars.", "Cuesta 15 dólares."),
        ("Ñoño señor.", "Ñoño señor."),  # letras latinas con tilde y eñe
    ],
)
def test_valid_translations_pass_the_filters(source: str, output: str) -> None:
    assert rejection_reason(source, output) is None


def test_all_the_outputs_of_the_contract_sentences_pass_the_filters() -> None:
    for source, output in KNOWN.items():
        assert rejection_reason(source, output) is None, source


# ---------------------------------------------------------------------------
# Errores del servidor
# ---------------------------------------------------------------------------
def raising(error: Exception) -> Callable[[dict[str, Any]], httpx.Response]:
    def responder(body: dict[str, Any]) -> httpx.Response:
        raise error

    return responder


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("conexión rechazada"),
        httpx.ReadTimeout("sin respuesta"),
        httpx.ConnectTimeout("sin conexión"),
        httpx.RemoteProtocolError("cortado"),
    ],
)
def test_network_errors_are_recoverable_engine_errors(error: Exception) -> None:
    translator, _ = make_translator(FakeChatServer(raising(error)))

    with pytest.raises(EngineError) as raised:
        translator.translate(make_request(1, "okay"))

    assert raised.value.recoverable is True
    assert raised.value.engine == "hy-mt2-7b-q4"
    assert raised.value.__cause__ is error


@pytest.mark.parametrize(
    ("status", "recoverable"), [(500, True), (502, True), (503, True), (400, False), (404, False)]
)
def test_http_errors_are_recoverable_only_if_they_are_not_a_client_error(
    status: int, recoverable: bool
) -> None:
    translator, _ = make_translator(
        FakeChatServer(lambda body: httpx.Response(status, text="fallo del servidor"))
    )

    with pytest.raises(EngineError) as raised:
        translator.translate(make_request(1, "okay"))

    assert raised.value.recoverable is recoverable
    assert str(status) in str(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="esto no es json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": None}]}),
        httpx.Response(200, json=["no", "es", "un", "objeto"]),
    ],
)
def test_an_invalid_response_is_an_engine_error(response: httpx.Response) -> None:
    translator, _ = make_translator(FakeChatServer(lambda body: response))

    with pytest.raises(EngineError) as raised:
        translator.translate(make_request(1, "okay"))

    assert raised.value.recoverable is True


def test_a_null_content_is_an_empty_translation_and_gets_rejected() -> None:
    response = httpx.Response(
        200, json={"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}
    )
    translator, _ = make_translator(FakeChatServer(lambda body: response))

    result = translator.translate(make_request(1, "okay"))

    assert result.rejected is True
    assert result.text == ""


def test_close_is_idempotent_and_translating_afterwards_is_an_engine_error() -> None:
    translator, _ = make_translator()
    translator.close()
    translator.close()

    with pytest.raises(EngineError) as raised:
        translator.translate(make_request(1, "okay"))

    assert raised.value.recoverable is False


# ---------------------------------------------------------------------------
# Con un servidor HTTP de verdad (el transporte por defecto, con TCP_NODELAY)
# ---------------------------------------------------------------------------
def test_the_default_transport_talks_to_a_real_http_server() -> None:
    received: list[tuple[str, dict[str, Any]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body))
            payload = json.dumps(
                {"choices": [{"message": {"content": "hola, amigo mío"}, "finish_reason": "stop"}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    translator = HyMt2Translator(f"http://127.0.0.1:{server.server_address[1]}", "7b")
    try:
        result = translator.translate(make_request(1, "hello there my friend"))
    finally:
        translator.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.text == "hola, amigo mío"
    assert result.rejected is False
    assert received[0][0] == "/v1/chat/completions"
    assert received[0][1]["messages"][-1]["content"].endswith("hello there my friend")


def test_an_unreachable_server_is_a_recoverable_engine_error() -> None:
    translator = HyMt2Translator(f"http://127.0.0.1:{find_free_port()}", "7b", timeout_s=2.0)  # nadie escucha
    try:
        with pytest.raises(EngineError) as raised:
            translator.translate(make_request(1, "okay"))
    finally:
        translator.close()

    assert raised.value.recoverable is True


# ---------------------------------------------------------------------------
# Constructores de mensajes sueltos
# ---------------------------------------------------------------------------
def test_build_normal_messages_matches_the_translator_request(no_base_glossary: None) -> None:
    translator, server = make_translator()
    context = (("Hi.", "Hola."),)

    translator.translate(make_request(1, "okay", context=context))

    assert server.messages == build_normal_messages("okay", context)


def test_the_fixed_examples_are_the_12_of_s2() -> None:
    assert len(hymt2.FEWSHOT_ES_ES) == 12
    assert hymt2.FEWSHOT_ES_ES[0] == S2_FIRST_SHOT
    assert hymt2.FEWSHOT_ES_ES[-1] == S2_LAST_SHOT


# ---------------------------------------------------------------------------
# Glosario base: glossary_es.toml
# ---------------------------------------------------------------------------
#: Pares que pide T022 como ejemplo.
TASK_EXAMPLES = {
    "juice": "zumo",
    "fridge": "nevera",
    "parking lot": "aparcamiento",
    "computer": "ordenador",
    "cell phone": "móvil",
    "car": "coche",
    "popcorn": "palomitas",
    "okay": "vale",
}
#: Palabras de español de América que no pueden aparecer en ningún destino del glosario.
LATIN_AMERICAN_WORDS = frozenset(
    {"jugo", "carro", "celular", "estacionamiento", "departamento", "refrigerador", "durazno", "papa"}
    | {"papas", "computadora", "ustedes", "popote", "playera", "tina", "cobija", "elevador", "mesero"}
    | {"mesera", "banqueta", "vereda", "cajuela", "manejar", "lentes", "pastel", "boleto", "tarea"}
    | {"frijoles", "camioneta"}
)
#: Frases de S2 que comprueban léxico de España, con los términos del glosario base que les corresponden.
S2_LEXICON_SENTENCES = {
    "Did you seriously finish the orange juice and put the empty carton back in the fridge?": {
        "juice",
        "fridge",
    },
    "Fine. I'll buy you another one tomorrow, okay?": {"okay"},
    "And promise me you won't tell Mom I took her car last night.": {"car"},
    "They found fibers under the victim's fingernails and a sneaker print by the window.": {"sneaker"},
    "None of it matches anything in her apartment.": {"apartment"},
    "Hold on, I can't find my cell phone.": {"cell phone"},
    "Did you two enjoy the movie, or was the popcorn the best part?": {"popcorn"},
    "Okay, everybody, grab your laptops and follow me. We're working in the parking lot today.": {
        "okay",
        "laptop",
        "parking lot",
    },
    "Can you pull over at the next gas station? I need a sandwich and a bathroom.": {"gas station"},
    "Deal. And grab the map out of the glove compartment.": {"glove compartment"},
    "Dude, nobody uses maps anymore. We have GPS.": {"dude"},
}


@pytest.fixture
def clean_glossary_caches() -> Iterator[None]:
    """Vacía las cachés del glosario antes y después: un test que cambia el fichero no contamina a otros."""
    hymt2.load_base_glossary.cache_clear()
    hymt2._base_matchers.cache_clear()
    yield
    hymt2.load_base_glossary.cache_clear()
    hymt2._base_matchers.cache_clear()


def test_the_base_glossary_is_a_resource_of_the_package() -> None:
    resource = resources.files("instanttraductor.mt").joinpath("glossary_es.toml")

    assert resource.is_file()
    assert hymt2.BASE_GLOSSARY_RESOURCE == "glossary_es.toml"


def test_the_base_glossary_has_at_least_150_pairs() -> None:
    assert len(load_base_glossary()) >= 150


def test_the_base_glossary_has_the_pairs_of_the_task() -> None:
    pairs = {entry.source: entry.target for entry in load_base_glossary()}

    for source, target in TASK_EXAMPLES.items():
        assert pairs[source] == target


def test_base_glossary_entries_are_well_formed() -> None:
    entries = load_base_glossary()
    sources = [entry.source for entry in entries]

    assert all(isinstance(entry, GlossaryEntry) for entry in entries)
    assert len({source.casefold() for source in sources}) == len(sources), "orígenes repetidos"
    assert all(source == source.strip().lower() and source for source in sources), "origen no en minúsculas"
    assert all(entry.target == entry.target.strip() and entry.target for entry in entries)
    # Sin artículo inicial: con artículo en los dos lados el modelo lo duplica (S2).
    assert not [e for e in entries if e.target.split()[0] in {"el", "la", "los", "las", "un", "una"}]


def test_no_base_term_contains_another_as_whole_words() -> None:
    """Sin solapes: «bus» dentro de «bus ticket» mandaría las dos filas al mismo *prompt*."""
    tokens = {entry.source: entry.source.split() for entry in load_base_glossary()}
    overlaps = [
        (small, big)
        for small, small_tokens in tokens.items()
        for big, big_tokens in tokens.items()
        if small != big
        and any(big_tokens[i : i + len(small_tokens)] == small_tokens for i in range(len(big_tokens)))
    ]

    assert overlaps == []


def test_base_glossary_targets_have_no_latin_american_words() -> None:
    bad = [e for e in load_base_glossary() if LATIN_AMERICAN_WORDS.intersection(e.target.lower().split())]

    assert bad == []


def test_the_base_glossary_is_loaded_once() -> None:
    assert load_base_glossary() is load_base_glossary()


@pytest.mark.parametrize(("sentence", "expected"), list(S2_LEXICON_SENTENCES.items()))
def test_the_base_glossary_covers_the_spain_lexicon_checked_in_s2(sentence: str, expected: set[str]) -> None:
    assert {entry.source for entry in select_glossary(sentence)} == expected


def test_sentences_without_base_terms_get_nothing() -> None:
    assert select_glossary("I think we should leave before it gets dark") == ()
    assert select_glossary("") == ()


def test_a_malformed_base_glossary_is_a_value_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clean_glossary_caches: None
) -> None:
    monkeypatch.setattr(hymt2.resources, "files", lambda package: tmp_path)
    for text in ("", "[otra]\nx = 'y'\n", "[terms]\n", "[terms]\njuice = 3\n", '[terms]\n"" = "zumo"\n'):
        (tmp_path / "glossary_es.toml").write_text(text, encoding="utf-8")
        hymt2.load_base_glossary.cache_clear()
        with pytest.raises(ValueError, match="glossary_es.toml"):
            load_base_glossary()


def test_the_base_glossary_can_be_replaced_by_another_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clean_glossary_caches: None
) -> None:
    (tmp_path / "glossary_es.toml").write_text('[terms]\n"Moon Base" = "Base Lunar"\n', encoding="utf-8")
    monkeypatch.setattr(hymt2.resources, "files", lambda package: tmp_path)

    assert select_glossary("Welcome to the moon base!") == (GlossaryEntry("Moon Base", "Base Lunar"),)


# ===========================================================================
# T017: traducción por idioma de origen (spec 002, research R10)
# ===========================================================================
def request_in(
    language: SourceLanguage,
    text: str,
    mode: TranslationMode = TranslationMode.NORMAL,
    *,
    context: tuple[tuple[str, str], ...] = (),
    glossary: tuple[GlossaryEntry, ...] = (),
) -> TranslationRequest:
    return replace(make_request(1, text, mode, context=context, glossary=glossary), source_language=language)


#: Frases reales de ``spikes/idiomas/traducciones_*.md`` (FLEURS, CC BY 4.0) con la traducción de Hy-MT2-7B
#: en S5. Con el filtro de 3x de la 001 se rechazaban 48 de 50 en chino; la relación aquí llega a 5.
CJK_SENTENCES: dict[SourceLanguage, tuple[tuple[str, str], ...]] = {
    SourceLanguage.ZH: (
        (
            "由于分离和重组，变异在每一代的两个库之间来回变动。",
            "Debido a la separación y reorganización, las mutaciones varían de un lado a otro entre las dos "
            "colecciones en cada generación.",
        ),
        (
            "该大学的研究人员表示，这两种化合物相互作用形成的晶体可能会造成肾脏功能障碍。",
            "Los investigadores de la universidad afirman que los cristales que se forman por la interacción "
            "de estos dos compuestos pueden causar problemas en el funcionamiento renal.",
        ),
        (
            "尽管如此，还是要听从有关部门的建议，遵守所有的标志并密切注意安全警告。",
            "Aun así, hay que seguir los consejos de las autoridades competentes, respetar todos los "
            "carteles y prestar mucha atención a las advertencias de seguridad.",
        ),
        (
            "它指出，对主体来说最有效的位置是将图像垂直和水平分为三部分的线的交叉点（见示例）。",
            "Se indica que la posición más eficaz para el sujeto es el punto de intersección de las líneas "
            "que dividen la imagen en tres partes vertical y horizontalmente (ver ejemplo).",
        ),
        (
            "古代文明和部落开始驯养它们，食用和使用它们的奶、肉、毛和皮。",
            "Las civilizaciones y tribus antiguas comenzaron a domesticarlos para consumir y utilizar su "
            "leche, carne, lana y piel.",
        ),
    ),
    SourceLanguage.JA: (
        (
            "しかし、現在も鳥の外観は多くの点で恐竜に似ています。",
            "Sin embargo, hoy en día la apariencia de las aves sigue siendo similar a la de los dinosaurios "
            "en muchos aspectos.",
        ),
        (
            "脳病理と行動の相関関係は、科学者たちの研究を裏付けるものです。",
            "La relación entre la patología cerebral y el comportamiento respalda las investigaciones de los "
            "científicos.",
        ),
        (
            "月面は岩石と塵でできています。月の外層は地殻と呼ばれています。",
            "La superficie lunar está formada por rocas y polvo. La capa externa de la Luna se llama "
            "corteza.",
        ),
        (
            "すべての名詞は、「あなた」を指す単語Sieと同様に、文の途中であっても常に大文字で始まります。",
            "Todos los sustantivos, al igual que la palabra Sie que se refiere a “tú”, siempre comienzan en "
            "mayúscula, incluso en medio de una oración.",
        ),
        (
            "それでも、当局からのアドバイスを受け、すべての標識を守り、安全上の警告に細心の注意を払いましょう。",
            "Aun así, sigamos los consejos de las autoridades, respetemos todos los carteles y prestemos "
            "mucha atención a las advertencias de seguridad.",
        ),
    ),
    SourceLanguage.KO: (
        (
            "유럽 역사의 이 시기에 부유하고 강력해진 가톨릭교회는 철저한 조사를 받았습니다.",
            "Durante este período de la historia europea, la Iglesia católica, que se había vuelto rica y "
            "poderosa, fue sometida a una investigación exhaustiva.",
        ),
        (
            "악천후는 피해, 심각한 사회 혼란 또는 인명 손실을 초래할 수 있는 위험한 기상 현상의 총칭이다.",
            "El mal tiempo es el término general para los fenómenos meteorológicos peligrosos que pueden "
            "causar daños, graves disturbios sociales o pérdida de vidas humanas.",
        ),
        (
            "쿤달리니 요가를 하면 요가 자세, 호흡 운동, 만트라 및 시각화를 통해 "
            "쿤달리니 에너지(계몽 에너지)가 깨어납니다.",
            "Al practicar el yoga Kundalini, la energía Kundalini (energía de iluminación) se despierta a "
            "través de posturas de yoga, ejercicios de respiración, mantras y visualización.",
        ),
        (
            "pH 레벨은 시험을 거친 화학 물질에서 수소(pH에서 H) 이온의 양으로 표시합니다.",
            "El nivel de pH indica la cantidad de iones de hidrógeno (H en el pH) en una sustancia química "
            "sometida a pruebas.",
        ),
        (
            "사막 모래의 영향으로 인해, 1990년 팀북투는 위험에 처한 세계 문화유산 목록에 추가되었습니다.",
            "Debido a los efectos de la arena del desierto, en 1990 Timbuktu fue incluida en la lista del "
            "Patrimonio Mundial en Peligro.",
        ),
    ),
}
CJK_CASES = [
    pytest.param(language, source, translation, id=f"{language.value}-{index}")
    for language, pairs in CJK_SENTENCES.items()
    for index, (source, translation) in enumerate(pairs)
]
OVER_THREE_TIMES = [case for case in CJK_CASES if len(case.values[2]) > 3 * len(case.values[1])]

NOTE_LITERAL = (
    '\n\n(Spanish from Spain, informal: use "vosotros" when you address several people, never "ustedes".)'
)
RETRY_LITERAL = (
    '\n\n(The listeners are several friends or colleagues: translate "you" as informal plural for Spain '
    '(use "vosotros" forms such as estáis, tenéis, venid, no os preocupéis; never "ustedes").)'
)


def test_the_real_fixtures_cover_the_three_languages_and_the_old_filter_would_reject_most() -> None:
    assert {case.values[0] for case in CJK_CASES} == {SourceLanguage.ZH, SourceLanguage.JA, SourceLanguage.KO}
    assert len(OVER_THREE_TIMES) >= 8


@pytest.mark.parametrize(("language", "source", "translation"), CJK_CASES)
def test_real_translations_pass_the_filters_of_their_source_language(
    language: SourceLanguage, source: str, translation: str
) -> None:
    assert rejection_reason(source, translation, source_language=language) is None


@pytest.mark.parametrize(("language", "source", "translation"), OVER_THREE_TIMES)
def test_the_english_length_filter_rejected_those_same_translations(
    language: SourceLanguage, source: str, translation: str
) -> None:
    assert rejection_reason(source, translation) == "longitud"
    assert rejection_reason(source, translation, source_language=SourceLanguage.EN) == "longitud"


@pytest.mark.parametrize(("language", "source", "translation"), CJK_CASES)
def test_the_translator_accepts_real_translations_in_each_language(
    language: SourceLanguage, source: str, translation: str
) -> None:
    translator, _ = make_translator(FakeChatServer(lambda body: chat_response(translation)))

    result = translator.translate(request_in(language, source))

    assert result.rejected is False
    assert result.text == translation


def test_the_same_chinese_translation_is_rejected_when_the_request_says_english() -> None:
    source, translation = CJK_SENTENCES[SourceLanguage.ZH][0]  # 5 veces el original
    translator, _ = make_translator(FakeChatServer(lambda body: chat_response(translation)))

    assert translator.translate(request_in(SourceLanguage.EN, source)).rejected is True
    assert translator.translate(request_in(SourceLanguage.ZH, source)).rejected is False


@pytest.mark.parametrize(
    ("language", "ratio"),
    [
        (SourceLanguage.EN, 3),
        (SourceLanguage.KO, 4),
        (SourceLanguage.JA, 6),
        (SourceLanguage.ZH, 7),
    ],
)
def test_the_length_limit_of_each_language(language: SourceLanguage, ratio: int) -> None:
    source = "一二三四五六七八九十"
    assert hymt2.MAX_LENGTH_RATIO_BY_LANGUAGE[language] == ratio
    assert rejection_reason(source, "a" * (ratio * len(source)), source_language=language) is None
    assert rejection_reason(source, "a" * (ratio * len(source) + 1), source_language=language) == "longitud"


def test_a_truncated_answer_is_rejected_in_every_language() -> None:
    for language in SourceLanguage:
        assert (
            rejection_reason("一二三", "Hola", finish_reason="length", source_language=language) == "longitud"
        )


def test_the_other_filters_do_not_depend_on_the_language() -> None:
    for language in SourceLanguage:
        assert rejection_reason("一二三", "", source_language=language) == "vacía"
        assert rejection_reason("一二三", "你好", source_language=language) == "idioma"
        echo = "Aquí tienes la traducción: hola"
        assert rejection_reason("一二三四五六七八九十" * 2, echo, source_language=language) == (
            "eco del prompt"
        )


def test_max_tokens_in_chinese_and_japanese_is_three_per_character() -> None:
    assert count_characters("你好，世界！ 1") == 5  # sin espacios ni signos
    for language in (SourceLanguage.ZH, SourceLanguage.JA):
        assert max_tokens_for("一" * 10, language) == 64  # el mínimo
        assert max_tokens_for("一" * 25, language) == 75
        assert max_tokens_for("一" * 100, language) == 300
        assert max_tokens_for("一" * 200, language) == 512  # el máximo


def test_a_cjk_sentence_is_not_one_word_for_max_tokens() -> None:
    source = CJK_SENTENCES[SourceLanguage.ZH][1][0]  # 38 caracteres, 3 palabras para count_words
    assert count_words(source) < 5
    assert max_tokens_for(source) == 64  # por palabras truncaba
    assert max_tokens_for(source, SourceLanguage.ZH) == 3 * count_characters(source) > 64


def test_max_tokens_in_korean_and_english_stays_per_word() -> None:
    korean = CJK_SENTENCES[SourceLanguage.KO][1][0]
    assert max_tokens_for(korean, SourceLanguage.KO) == max_tokens_for(korean)
    assert max_tokens_for(korean, SourceLanguage.KO) == min(512, max(64, 4 * count_words(korean)))
    assert max_tokens_for("one two three", SourceLanguage.EN) == 64


def test_the_request_to_the_server_uses_the_max_tokens_of_the_language() -> None:
    source = CJK_SENTENCES[SourceLanguage.ZH][1][0]
    translator, server = make_translator()

    translator.translate(request_in(SourceLanguage.ZH, source))

    assert server.bodies[0]["max_tokens"] == 3 * count_characters(source)


@pytest.mark.parametrize(
    ("language", "name"),
    [(SourceLanguage.JA, "Japanese"), (SourceLanguage.ZH, "Chinese"), (SourceLanguage.KO, "Korean")],
)
def test_the_prompt_names_the_source_language(
    language: SourceLanguage, name: str, no_base_glossary: None
) -> None:
    translator, server = make_translator()
    context = (("元の文", "La frase original."),)

    translator.translate(request_in(language, "ありがとう", context=context))

    messages = server.messages
    assert messages[0]["content"].startswith(f"Translate every user message from {name} into Spanish. ")
    assert messages[0]["content"].endswith(
        S2_SYSTEM.removeprefix("Translate every user message into Spanish. ")
    )
    assert messages[-1] == {
        "role": "user",
        "content": (
            f"Translate the following {name} text into Spanish. Note that you must ONLY output the "
            "translated result without any additional explanation:\n\nありがとう"
        ),
    }
    # Los ejemplos y el contexto, con la plantilla genérica (el prefijo cacheado no cambia por frase).
    assert messages[1] == {"role": "user", "content": S2_WRAPPER + S2_FIRST_SHOT[0]}
    assert messages[-3] == {"role": "user", "content": S2_WRAPPER + "元の文"}
    assert len(messages) == 1 + 2 * 12 + 2 + 1


def test_english_keeps_the_prompt_measured_in_s2(no_base_glossary: None) -> None:
    translator, server = make_translator()

    translator.translate(request_in(SourceLanguage.EN, "okay"))

    assert server.messages[0] == {"role": "system", "content": S2_SYSTEM}
    assert server.messages[-1] == {"role": "user", "content": S2_WRAPPER + "okay"}


def test_the_prefix_up_to_the_context_is_identical_between_sentences_of_the_same_language(
    no_base_glossary: None,
) -> None:
    translator, server = make_translator()

    translator.translate(request_in(SourceLanguage.JA, "ありがとう"))
    translator.translate(request_in(SourceLanguage.JA, "さようなら", context=(("ありがとう", "Gracias."),)))

    assert server.bodies[0]["messages"][:-1] == server.bodies[1]["messages"][:25]


def test_the_base_glossary_only_acts_with_english_as_source() -> None:
    sentence = "put the juice in the fridge"
    assert {e.source for e in select_glossary(sentence)} == {"juice", "fridge"}
    assert {e.source for e in select_glossary(sentence, source_language=SourceLanguage.EN)} == {
        "juice",
        "fridge",
    }
    for language in (SourceLanguage.JA, SourceLanguage.ZH, SourceLanguage.KO):
        assert select_glossary(sentence, source_language=language) == ()


def test_the_user_glossary_still_applies_in_every_language() -> None:
    user = (GlossaryEntry("エンバー宮廷", "Corte de Ascuas"),)
    for language in (SourceLanguage.JA, SourceLanguage.ZH, SourceLanguage.KO):
        assert select_glossary("juice fridge", user, source_language=language) == user


def test_a_japanese_request_gets_no_base_terminology_but_does_get_the_users() -> None:
    translator, server = make_translator()

    translator.translate(request_in(SourceLanguage.JA, "juice を fridge に入れて"))
    assert "参考" not in server.messages[-1]["content"]

    user = (GlossaryEntry("エンバー宮廷", "Corte de Ascuas"),)
    translator.translate(request_in(SourceLanguage.JA, "エンバー宮廷の門が閉まった", glossary=user))
    assert terminology_rows(server.messages[-1]["content"]) == ["エンバー宮廷 翻译成 Corte de Ascuas"]


def test_the_concise_budget_of_chinese_and_japanese_is_estimated_from_the_characters() -> None:
    twenty = "一二三四五六七八九十" * 2
    assert concise_word_budget(twenty, SourceLanguage.ZH) == 6  # ceil(0,6 * ceil(0,5 * 20))
    assert concise_word_budget(twenty, SourceLanguage.JA) == 8  # ceil(0,6 * ceil(0,65 * 20))
    assert concise_word_budget("하나 둘 셋 넷 다섯", SourceLanguage.KO) == 3  # por palabras, como en
    assert concise_word_budget("one two three four five") == 3
    assert concise_word_budget("", SourceLanguage.ZH) == 1


def test_the_concise_prompt_names_the_source_language() -> None:
    twenty = "一二三四五六七八九十" * 2
    translator, server = make_translator()

    result = translator.translate(request_in(SourceLanguage.JA, twenty, TranslationMode.CONCISE))

    assert result.mode is TranslationMode.CONCISE
    [message] = server.messages
    assert message["content"].startswith("Please translate the following Japanese text into Spanish. ")
    assert "at most 8 words" in message["content"]
    assert message["content"].endswith("]:\n\n" + twenty)
    assert build_concise_messages(twenty, source_language=SourceLanguage.JA) == server.messages


# ===========================================================================
# T018: «vosotros» (spec 002, research R8)
# ===========================================================================
GROUP_CONTEXT = (("Alright, everybody, gather around.", "Vale, todos, acercaos."),)


def test_the_first_pass_never_carries_the_note(no_base_glossary: None) -> None:
    translator, server = make_translator(FakeChatServer(lambda body: chat_response("Vale, ¿lo entendéis?")))

    translator.translate(make_request(1, "Do you understand?", context=GROUP_CONTEXT))

    assert len(server.bodies) == 1  # ya sale «vosotros»: sin reintento
    assert server.messages[-1] == {"role": "user", "content": S2_WRAPPER + "Do you understand?"}


def test_the_retry_keeps_the_cached_prefix_of_the_prompt(no_base_glossary: None) -> None:
    server = FakeChatServer(retry_responder("¿Lo entiendes?", "¿Lo entendéis?"))
    translator, _ = make_translator(server)

    translator.translate(make_request(1, "Do you understand?", context=GROUP_CONTEXT))

    first, retried = server.bodies[0]["messages"], server.bodies[1]["messages"]
    assert retried[:25] == first[:25]  # sistema y 12 ejemplos
    assert retried[-1]["content"] == S2_WRAPPER + "Do you understand?" + RETRY_LITERAL


def test_the_retry_note_also_follows_the_terminology_turn(no_base_glossary: None) -> None:
    server = FakeChatServer(retry_responder("La Corte de Ascuas llama.", "Os llama la Corte de Ascuas."))
    translator, _ = make_translator(server)
    glossary = (GlossaryEntry("Ember Court", "Corte de Ascuas"),)

    translator.translate(make_request(1, "The Ember Court calls.", context=GROUP_CONTEXT, glossary=glossary))

    content = server.bodies[1]["messages"][-1]["content"]
    assert content.startswith("参考下面的翻译：\nEmber Court 翻译成 Corte de Ascuas")
    assert content.endswith("The Ember Court calls." + RETRY_LITERAL)


def test_a_plural_marker_without_vosotros_in_the_answer_triggers_the_retry(no_base_glossary: None) -> None:
    server = FakeChatServer(retry_responder("¿Listos?", "¿Estáis listos?"))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, "Are you guys ready?"))

    assert len(server.bodies) == 2
    assert result.text == "¿Estáis listos?"


@pytest.mark.parametrize(
    ("text", "context"),
    [
        ("Do you understand?", ()),
        ("Do you understand?", (("Open your books to page twelve.", "Abrid los libros en la página doce."),)),
        ("Do you understand?", (*GROUP_CONTEXT, ("Hey, buddy, come here.", "Oye, amigo, ven."))),
        ("Sir, are you guys coming?", GROUP_CONTEXT),
        (
            "Do you understand?",
            (GROUP_CONTEXT[0], *[(f"Line {n}.", f"Línea {n}.") for n in range(5)]),
        ),  # el plural queda fuera de las últimas 5
    ],
)
def test_without_a_group_signal_there_is_no_retry(
    text: str, context: tuple[tuple[str, str], ...], no_base_glossary: None
) -> None:
    translator, server = make_translator(FakeChatServer(lambda body: chat_response("¿Lo entiendes?")))

    translator.translate(make_request(1, text, context=context))

    assert len(server.bodies) == 1
    assert server.messages[-1]["content"] == S2_WRAPPER + text


def test_the_plural_marker_four_lines_back_still_counts(no_base_glossary: None) -> None:
    server = FakeChatServer(retry_responder("¿Lo entiendes?", "¿Lo entendéis?"))
    translator, _ = make_translator(server)
    context = (GROUP_CONTEXT[0], *[(f"Line {n}.", f"Línea {n}.") for n in range(4)])

    result = translator.translate(make_request(1, "Do you understand?", context=context))

    assert len(server.bodies) == 2
    assert result.text == "¿Lo entendéis?"


@pytest.mark.parametrize("language", [SourceLanguage.JA, SourceLanguage.ZH, SourceLanguage.KO])
def test_the_note_is_only_for_english_sources(language: SourceLanguage, no_base_glossary: None) -> None:
    translator, server = make_translator()

    translator.translate(request_in(language, "皆さん、準備はいいですか", context=GROUP_CONTEXT))

    assert "vosotros" not in json.dumps(server.messages[-1], ensure_ascii=False)


def test_concise_mode_has_the_informal_register_in_its_style_clause_and_no_note() -> None:
    translator, server = make_translator()

    translator.translate(
        make_request(1, "Are you guys ready?", TranslationMode.CONCISE, context=GROUP_CONTEXT)
    )

    [message] = server.messages
    assert message["content"].count("vosotros") == 1
    assert 'several listeners = "vosotros" (estáis, tenéis, venid), one listener = "tú"' in message["content"]
    assert "never" not in message["content"]  # la nota del modo normal no va en CONCISE


def test_the_note_the_model_repeats_is_cut_before_the_filters() -> None:
    echoed = "¿Tenéis hambre?" + "\n\n(Español de España, informal: usa «vosotros» cuando hables a varios.)"
    translator, _ = make_translator(FakeChatServer(lambda body: chat_response(echoed)))

    result = translator.translate(make_request(1, "Are you hungry, guys?", context=GROUP_CONTEXT))

    assert result.rejected is False
    assert result.text == "¿Tenéis hambre?"


def test_without_the_cut_that_echo_would_have_been_rejected_for_its_length() -> None:
    echoed = "¿Tenéis hambre?" + "\n\n(Español de España, informal: usa «vosotros» cuando hables a varios.)"
    assert rejection_reason("Are you hungry, guys?", echoed) == "longitud"


def test_the_cut_also_applies_without_a_group_note() -> None:
    translator, _ = make_translator(FakeChatServer(lambda body: chat_response("Hola.\n\n(Nota: saludo)")))

    result = translator.translate(make_request(1, "Hello there, friend"))

    assert result.text == "Hola."


def test_the_translation_is_post_edited_with_the_english_signal() -> None:
    translator, server = make_translator(FakeChatServer(lambda body: chat_response("¿Están ustedes listos?")))

    result = translator.translate(make_request(1, "Are you guys ready?"))

    assert result.text == "¿Estáis vosotros listos?"
    assert len(server.bodies) == 1  # no queda «ustedes»: sin reintento


def test_the_postedit_also_applies_in_concise_mode() -> None:
    translator, _ = make_translator(FakeChatServer(lambda body: chat_response("Tomen asiento, todos.")))

    result = translator.translate(make_request(1, "Take a seat, everyone.", TranslationMode.CONCISE))

    assert result.text == "Tomad asiento, todos."
    assert result.mode is TranslationMode.CONCISE


def test_the_postedit_never_touches_a_japanese_translation() -> None:
    translator, _ = make_translator(FakeChatServer(lambda body: chat_response("¿Están ustedes listos?")))

    result = translator.translate(request_in(SourceLanguage.JA, "皆さん、準備はいいですか？"))

    assert result.text == "¿Están ustedes listos?"


def test_a_singular_sentence_is_not_damaged_by_the_pipeline() -> None:
    translator, server = make_translator(
        FakeChatServer(lambda body: chat_response("¿Has terminado los deberes?"))
    )

    result = translator.translate(make_request(1, "Did you finish your homework?"))

    assert result.text == "¿Has terminado los deberes?"
    assert len(server.bodies) == 1


# --- Reintento --------------------------------------------------------------------------------------------
def retry_responder(first: str, second: str) -> Callable[[dict[str, Any]], httpx.Response]:
    """Responde ``first`` a la petición normal y ``second`` a la que lleva la nota del reintento."""

    def respond(body: dict[str, Any]) -> httpx.Response:
        retried = body["messages"][-1]["content"].endswith(RETRY_LITERAL)
        return chat_response(second if retried else first)

    return respond


#: «they» + «ustedes»: la posedición lo deja (ambiguo) y «you guys» da la señal de grupo.
AMBIGUOUS = "They are late, you guys."


def test_a_residual_ustedes_with_a_group_signal_retries_once_with_the_retry_note() -> None:
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", "Llegáis tarde, ¿eh?"))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, AMBIGUOUS))

    assert result.text == "Llegáis tarde, ¿eh?"
    assert len(server.bodies) == 2
    first, second = server.bodies[0]["messages"], server.bodies[1]["messages"]
    assert second[:-1] == first[:-1]
    assert second[-1]["content"] == first[-1]["content"] + RETRY_LITERAL
    assert second[-1]["role"] == "user"
    assert second is not first
    assert server.bodies[1]["max_tokens"] == server.bodies[0]["max_tokens"]


def test_the_retry_is_made_only_once_even_if_it_still_says_ustedes() -> None:
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", "Ustedes llegáis tarde."))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, AMBIGUOUS))

    assert len(server.bodies) == 2
    assert result.text == "Ustedes llegan tarde."  # se queda la primera


@pytest.mark.parametrize(
    "second",
    [
        "Llegan tarde.",  # ni «vosotros» ni «ustedes»
        "你们迟到了",  # el filtro de idioma la rechaza
        "",
        # demasiado larga: más de 3 veces el original
        "Llegáis tarde, vosotros y ustedes, y además no avisáis de nada porque os da lo mismo.",
    ],
)
def test_a_retry_that_is_not_better_keeps_the_first_translation(second: str) -> None:
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", second))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, AMBIGUOUS))

    assert len(server.bodies) == 2
    assert result.text == "Ustedes llegan tarde."
    assert result.rejected is False


def test_a_retry_that_fails_keeps_the_first_translation() -> None:
    def respond(body: dict[str, Any]) -> httpx.Response:
        if body["messages"][-1]["content"].endswith(RETRY_LITERAL):
            return httpx.Response(500, text="boom")
        return chat_response("Ustedes llegan tarde.")

    translator, server = make_translator(FakeChatServer(respond))

    result = translator.translate(make_request(1, AMBIGUOUS))

    assert len(server.bodies) == 2
    assert result.text == "Ustedes llegan tarde."


def test_a_retry_that_repeats_the_note_is_cleaned_like_the_first_attempt() -> None:
    second = "Llegáis tarde.\n\n(Español de España: vosotros)"
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", second))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, AMBIGUOUS))

    assert result.text == "Llegáis tarde."


def test_no_retry_without_a_group_signal() -> None:
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", "Llegáis tarde."))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, "They are late."))

    assert len(server.bodies) == 1
    assert result.text == "Ustedes llegan tarde."


def test_no_retry_with_a_singular_marker_in_the_sentence() -> None:
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", "Llegáis tarde."))
    translator, _ = make_translator(server)

    translator.translate(make_request(1, "They are late, sir, you guys.", context=GROUP_CONTEXT))

    assert len(server.bodies) == 1


def test_the_group_signal_can_come_from_the_scene() -> None:
    server = FakeChatServer(retry_responder("¿Lo entiendes?", "¿Lo entendéis?"))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, "Do you understand?", context=GROUP_CONTEXT))

    assert len(server.bodies) == 2
    assert result.text == "¿Lo entendéis?"


def test_a_residual_ustedes_without_you_in_the_english_is_not_retried() -> None:
    """Sin «you», «ustedes» suele ser un «they» mal traducido: pasarlo a «vosotros» lo empeoraría."""
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", "Llegáis tarde."))
    translator, _ = make_translator(server)

    translator.translate(make_request(1, "They are late.", context=GROUP_CONTEXT))

    assert len(server.bodies) == 1


def test_no_retry_when_the_postedit_already_removed_the_ustedes() -> None:
    server = FakeChatServer(retry_responder("¿Están ustedes listos?", "no debería llegar"))
    translator, _ = make_translator(server)

    translator.translate(make_request(1, "Are you guys ready?"))

    assert len(server.bodies) == 1


def test_no_retry_in_concise_mode() -> None:
    server = FakeChatServer(lambda body: chat_response("Ustedes tarde."))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, AMBIGUOUS, TranslationMode.CONCISE))

    assert len(server.bodies) == 1
    assert result.text == "Ustedes tarde."


@pytest.mark.parametrize("language", [SourceLanguage.JA, SourceLanguage.ZH, SourceLanguage.KO])
def test_no_retry_for_cjk_sources(language: SourceLanguage) -> None:
    server = FakeChatServer(lambda body: chat_response("Ustedes llegan tarde."))
    translator, _ = make_translator(server)

    result = translator.translate(request_in(language, "皆さん遅いですよ", context=GROUP_CONTEXT))

    assert len(server.bodies) == 1
    assert result.text == "Ustedes llegan tarde."


def test_no_retry_when_the_first_translation_was_rejected() -> None:
    server = FakeChatServer(lambda body: chat_response("你们迟到了"))
    translator, _ = make_translator(server)

    result = translator.translate(make_request(1, AMBIGUOUS))

    assert len(server.bodies) == 1
    assert result.rejected is True


def test_the_retry_also_works_with_the_1_8b() -> None:
    server = FakeChatServer(retry_responder("Ustedes llegan tarde.", "Llegáis tarde."))
    translator, _ = make_translator(server, kind=MtModel.HY_MT2_1_8B)

    result = translator.translate(make_request(1, AMBIGUOUS))

    assert result.text == "Llegáis tarde."
