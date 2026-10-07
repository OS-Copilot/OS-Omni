# OpenPhotoEdit source photos (reconstructed)

The reviewed OpenPhotoEdit tasks read their source photos from
`/home/user/Desktop/attachment` in the author's `photo2`/`s1` snapshots, which
were never published. These files stand in for them: each one is the canvas
of the author's screen recording (CUA-Tasks-Review run artifacts) right after
the photo was imported and before any edit, cropped, upscaled to the original
1536x1024 and with the RGB calibration squares redrawn in pure primaries at
their recorded position. They are PNG data under the original `.jpg` names,
like the originals.

| file | recording frame |
|---|---|
| city_night_street.jpg | openphoto city_night_dual_export, 0:01:03 |
| city_night_storefront.jpg | openphoto city_night_dual_export, 0:15:49 |
| station_platform_wide.jpg | openphoto station_platform_dual_export, 0:01:07 |
| station_train_arrival.jpg | openphoto station_platform_dual_export, 0:09:13 |
| portrait_window_before.jpg | openphotoedit window_portrait_dual_export, 0:00:57 |
| portrait_window_detail.jpg | openphotoedit window_portrait_dual_export, 0:13:38 |

`initializers.linux.cua_review.seed_bundled_attachments` uploads a file only
when the guest lacks it, so a VM that has the real originals keeps them.
