from tools.inventory.gen_fault_catalog import build_catalog


def _fixture():
    return {
        "iot": {
            "27": {"fault_name": "FAULT_HUMAN_DETECTED", "messageType": "工作消息",
                   "can_suppress": 1, "lang": {
                       "en": {"popup": "", "alert": "Human entry detected.",
                              "resident": "Human presence detected.",
                              "detailTitle": "Human", "detail": "step1\\nstep2"},
                       "nb": {"popup": "", "alert": "Menneske oppdaget.",
                              "resident": "", "detailTitle": "", "detail": ""}}},
            "0": {"fault_name": "FAULT_HANGING", "messageType": "异常",
                  "can_suppress": 0, "lang": {
                      "en": {"popup": "Robot lifted.", "alert": "",
                             "resident": "Robot lifted.", "detailTitle": "Lifted",
                             "detail": "a"}}},
        },
        "heartbeat": {},
    }


def test_build_catalog_transforms():
    cat = build_catalog(_fixture())
    e = cat["iot"]["27"]
    assert e["fault_name"] == "FAULT_HUMAN_DETECTED"
    assert e["category"] == "FAULT"
    assert e["severity"] == "work_message"
    assert e["can_suppress"] is True
    assert e["lang"]["en"]["detail"] == "step1\nstep2"
    assert e["lang"]["nb"]["alert"] == "Menneske oppdaget."
    assert cat["iot"]["0"]["severity"] == "anomaly"
    assert cat["meta"]["langs"] == ["en", "nb"]
    assert "heartbeat" in cat


def test_build_catalog_unknown_severity_is_unknown():
    fx = {"iot": {"9": {"fault_name": "INFO_X", "messageType": None,
                        "can_suppress": 0, "lang": {}}}, "heartbeat": {}}
    cat = build_catalog(fx)
    assert cat["iot"]["9"]["severity"] == "unknown"
    assert cat["iot"]["9"]["category"] == "INFO"
