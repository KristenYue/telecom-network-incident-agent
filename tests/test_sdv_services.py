import pytest

from telecom_incident_agent.sdv_services import (
    SomeIpMessage,
    decode_dtcs,
    decode_snapshot,
    decode_someip,
    encode_someip,
)


def test_someip_round_trip_and_exact_length_validation():
    message = SomeIpMessage(0x1234, 1, 7, 9, 0, 0, b"abc")
    assert decode_someip(encode_someip(message)) == message
    with pytest.raises(ValueError, match="length"):
        decode_someip(encode_someip(message) + b"x")


def test_snapshot_decoder_rejects_non_boolean_wire_value():
    assert decode_snapshot(bytes.fromhex("30394b0001"))["speed_kph"] == 123.45
    with pytest.raises(ValueError, match="contract"):
        decode_snapshot(bytes.fromhex("30394b0201"))


def test_dtc_decoder_preserves_status_and_rejects_trailing_bytes():
    payload = bytes.fromhex("0001c40001020500000002")
    record = decode_dtcs(payload)[0]
    assert record == {
        "code": "0xC40001", "severity": 2, "test_failed": True,
        "pending": False, "confirmed": True, "occurrence_count": 2,
    }
    with pytest.raises(ValueError, match="length"):
        decode_dtcs(payload + b"x")
