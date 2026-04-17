## Contributing

This is an actively reverse-engineered fork focused on the Dreame A2 (`dreame.mower.g2408`). Contributions that advance g2408 support are welcome:

1. Fork [okolbu/ha-dreame-a2-mower](https://github.com/okolbu/ha-dreame-a2-mower) to your GitHub account.
2. Create a feature branch (`git checkout -b feat/your-change`) from `main`.
3. Open a pull request against `main` with a clear description of what the change does and how it was tested.

### Scope

Please keep contributions scoped to:
- Dreame A2 (`dreame.mower.g2408`) support.
- Improvements to protocol decoding, entity mapping, map overlay, or credentials hygiene.

Out of scope (these belong in the [upstream project](https://github.com/nicolasglg/dreame-mova-mower)):
- Other Dreame mower models or vacuums.
- MOVA or Mi branded devices.

### Design documents

Design specs live in [`docs/superpowers/specs/`](docs/superpowers/specs/) and implementation plans in [`docs/superpowers/plans/`](docs/superpowers/plans/). If you're proposing a substantial change, please read or write a short design document first so we can align on approach before code review.
