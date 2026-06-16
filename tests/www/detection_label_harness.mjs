import assert from "node:assert";
import { detectionLabel }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-core.js";

// Label format requested by the user: "<conf>% - <class>", confidence rounded,
// class + confidence taken straight from the JPEG COM detection.
assert.strictEqual(detectionLabel({ cls: "person", conf: 0.79 }), "79% - person");
assert.strictEqual(detectionLabel({ cls: "hedgehog", conf: 0.14 }), "14% - hedgehog");
// Rounding + missing fields are tolerated.
assert.strictEqual(detectionLabel({ cls: "person", conf: 0.005 }), "1% - person");
assert.strictEqual(detectionLabel({ cls: "object" }), "0% - object");
assert.strictEqual(detectionLabel({ conf: 0.5 }), "50% - ?");
assert.strictEqual(detectionLabel(null), "0% - ?");

console.log("OK");
