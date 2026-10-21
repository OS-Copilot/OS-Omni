Place the required local image assets for the GIMP green-apple task in this folder.

Required files:
- source image, any one of:
  - `Apple_and_Orange.jpg`
  - `Apple_and_Orange.jpg.jpg`
- reference image, any one of:
  - `Apple_and_Orange_expected.png`
  - `Apple_and_Orange_expected.png.png`
  - `Apple_and_Orange_expected.jpg`
  - `Apple_and_Orange_expected.jpg.jpg`

The reference output should be the intended final result:
- the full image with the default Focus Blur effect applied
- rotated upside down
- converted to black and white
- colors linearly inverted

The task init uploads both files into the Windows guest and opens GIMP, but it
does not open the source image for the agent. The task instruction tells the
agent to open `Apple_and_Orange.jpg` from the Downloads folder and export the
finished result as `apple_and_orange_focus_blur_submission.png`.
