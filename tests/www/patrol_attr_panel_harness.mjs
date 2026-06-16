import assert from "node:assert";
import { patrolConfigServiceData }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js";

const obj = { id: 3, kind: "patrol", cycles: 1, auto_capture: false };
assert.deepStrictEqual(
  patrolConfigServiceData(0, obj, { cycles: 3 }),
  { map_id: 0, point_id: 3, cycles: 3, auto_capture: false },
  "cycles change keeps current auto_capture",
);
assert.deepStrictEqual(
  patrolConfigServiceData(1, obj, { auto_capture: true }),
  { map_id: 1, point_id: 3, cycles: 1, auto_capture: true },
  "auto change keeps current cycles",
);
console.log("OK");
