"""Tests de ``mt/hymt2.py``: ``HyMt2Translator`` con un ``llama-server`` falso (``httpx.MockTransport``).

Sin GPU ni modelos. El texto del *prompt* se compara con el literal de S2 (``spikes/traduccion/README.md``,
«Prompt final»), no con las constantes del módulo: si alguien las toca, estos tests avisan.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from instanttraductor.contracts import (
    EngineError,
    GlossaryEntry,
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
    count_words,
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
    [(1, 1), (2, 2), (3, 3), (5, 5), (9, 8), (10, 9), (20, 17), (100, 81), (200, 161)],
)
def test_the_concise_budget_is_ceil_of_0_7_times_1_15_times_the_words(n_words: int, budget: int) -> None:
    assert concise_word_budget(" ".join(["word"] * n_words)) == budget


def test_the_concise_budget_has_a_floor_of_one_word() -> None:
    assert concise_word_budget("") == 1
    assert concise_word_budget("... ?!") == 1


def test_concise_mode_is_a_single_style_message_with_the_word_budget() -> None:
    translator, server = make_translator()
    text = "I think we should leave before it gets dark"  # 9 palabras -> N = 8

    result = translator.translate(make_request(1, text, TranslationMode.CONCISE))

    assert result.mode is TranslationMode.CONCISE
    assert server.messages == [{"role": "user", "content": CONCISE_PREFIX + "8 words]:\n\n" + text}]
    assert server.bodies[0]["cache_prompt"] is True


def test_concise_mode_ignores_context_and_the_fixed_examples() -> None:
    translator, server = make_translator()

    translator.translate(make_request(1, "okay", TranslationMode.CONCISE, context=(("Hi.", "Hola."),)))

    assert len(server.messages) == 1
    assert "Hola." not in server.messages[0]["content"]


def test_build_concise_messages_accepts_an_explicit_budget() -> None:
    assert build_concise_messages("one two three", 2) == [
        {"role": "user", "content": CONCISE_PREFIX + "2 words]:\n\none two three"}
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
