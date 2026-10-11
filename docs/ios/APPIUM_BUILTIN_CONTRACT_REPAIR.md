# Appium builtin contract repair

The iOS system prompt promises simple Python builtins alongside the existing Appium driver. The execution namespace omitted Python's side-effect-free repr builtin. A valid driver-value debug expression therefore raised NameError and incorrectly terminated the episode as outside_appium_framework.

The repair adds only repr to the existing builtin mapping. Task, evaluator, model configuration, step limit, import prohibition and host-access prohibition remain unchanged. A neutral regression fails before the one-line repair and passes afterward. Seven focused tests pass; real simulator execution confirms print(repr(driver.get_window_size())) succeeds, while code containing import time is still rejected before execution.

The first Flow rework attempt (51 steps) is preserved and excluded as an executor defect. Its captured native database contains five transactions; required transfer and income are absent, but the premature runtime termination prevents assigning this run a model-failure score. A fresh model run is required. Earlier valid Contacts and Flow expense results are unaffected: their terminal policy failures were explicit forbidden imports, not missing repr.

Source hashes:

Original executor SHA256: 5a406dc72d0d3f0f4f970c0abdd6a747ca780dc2eb81cb5bbc3a4f6dc1a4522d

Repaired executor SHA256: 2a6670705b966d83d1ad771ef3900a7c2af2cc6a25781b2b37fed5cf2c155f7d
