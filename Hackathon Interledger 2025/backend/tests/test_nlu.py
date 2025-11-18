import nlu


def test_consultar_saldo_intent():
    result = nlu.parse_text("Quiero consultar mi saldo")
    assert result["intent"]["name"] == nlu.INTENT_CONSULTAR_SALDO


def test_transferir_intent_with_entities():
    text = "Por favor transferir 150.50 a 012345678901234567"
    result = nlu.parse_text(text)
    assert result["intent"]["name"] == nlu.INTENT_TRANSFERIR
    assert result["entities"]["amount"] == 150.50
    assert result["entities"]["destination_account"] == "012345678901234567"


def test_desconocido_intent():
    result = nlu.parse_text("Texto que no tiene sentido financiero")
    assert result["intent"]["name"] == nlu.INTENT_DESCONOCIDO
