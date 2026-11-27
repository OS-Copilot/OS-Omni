# OpenPhotoEdit Flutter

This Flutter project provides the shared Material 3 editor used by the
OpenPhotoEdit Web and iOS targets.

```sh
flutter analyze
flutter test
flutter build web
flutter build ios --no-codesign
```

The app bundles the same generated portrait and landscape samples used by the
native Android target, so Web and iOS open real sample photos instead of
placeholder artwork.

On iOS, **Save** opens a filename prompt and writes the selected bundled sample
unchanged to the app documents directory at `OpenPhotoEdit/Exports`. The export
store sanitizes path separators and retains the sample's PNG bytes. Verify it
with `flutter analyze`, `flutter test`, and
`flutter build ios --simulator --no-codesign`.
