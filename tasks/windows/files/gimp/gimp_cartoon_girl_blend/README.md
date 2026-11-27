Place the local assets for this task in this folder before running:

Source background image accepted names:
- `Background_Scene.jpg`
- `Background_Scene.jpeg`
- `Background_Scene.jpg.png`
- `Background_Scene.jpeg.png`
- `Background_Scene.png.jpg`
- `Background_Scene.png.jpeg`
- `Background_Scene.png`
- `Background_Scene.jpg.jpg`
- `Background_Scene.jpeg.jpeg`
- `Background_Scene.png.png`

Source cartoon character image accepted names:
- `Cartoon_Girl.jpg`
- `Cartoon_Girl.jpeg`
- `Cartoon_Girl.jpg.png`
- `Cartoon_Girl.jpeg.png`
- `Cartoon_Girl.png.jpg`
- `Cartoon_Girl.png.jpeg`
- `Cartoon_Girl.png`
- `Cartoon_Girl.jpg.jpg`
- `Cartoon_Girl.jpeg.jpeg`
- `Cartoon_Girl.png.png`

Deterministic expected composite accepted names:
- `Composite_Expected.jpg`
- `Composite_Expected.jpeg`
- `Composite_Expected.jpg.png`
- `Composite_Expected.jpeg.png`
- `Composite_Expected.png.jpg`
- `Composite_Expected.png.jpeg`
- `Composite_Expected.png`
- `Composite_Expected.jpg.jpg`
- `Composite_Expected.jpeg.jpeg`
- `Composite_Expected.png.png`

The task initializer copies the first matching asset of each type into the
Windows guest Downloads folder with canonical names:
- `Background_Scene.png`
- `Cartoon_Girl.png`
- `Composite_Expected.png`

The agent must export the finished composite to Downloads. The evaluator
accepts these output filenames:
- `cartoon_girl_blend_submission.jpg`
- `cartoon_girl_blend_submission.jpg.png`
- `cartoon_girl_blend_submission.png.jpg`
- `cartoon_girl_blend_submission.png`
- `cartoon_girl_blend_submission.jpg.jpg`
- `cartoon_girl_blend_submission.png.png`
