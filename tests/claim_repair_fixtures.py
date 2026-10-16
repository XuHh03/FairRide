"""Express existing corrected-argument fixtures in the claim-patch wire format."""


def patch_response(output, payload):
    if payload.get("output_schema", {}).get("title") != "AdvocateRepair":
        return output
    return {"patches": [{"section": item["section"], "index": item["index"],
                         "replacement": output[item["section"]][item["index"]]}
                        for item in payload["schema_correction"]["claim_feedback"]]}
