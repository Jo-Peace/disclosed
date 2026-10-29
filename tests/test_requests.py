from pathlib import Path
from disclosed.providers.meta import MetaProvider
from disclosed.providers.base import FileInput
from disclosed.schema import PTR_SCHEMA

def test_meta_request_shape(tmp_path):
    p = tmp_path / "x.pdf"; p.write_bytes(b"%PDF-1.4 test")
    body = MetaProvider().build_request(system="s", user="u", schema=PTR_SCHEMA, schema_name="ptr", files=[FileInput(p)],
                                        reasoning_effort="medium", max_output_tokens=100)
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["name"] == "ptr" and "schema" in fmt
    part = body["input"][1]["content"][1]
    assert part["type"] == "input_file" and part["file_data"].startswith("data:application/pdf;base64,")
    assert body["reasoning"] == {"effort": "medium"} and "response_format" not in body
