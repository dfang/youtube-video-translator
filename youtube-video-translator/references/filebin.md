# Filebin API (Preview Upload)

Use Filebin to upload `final_video.mp4` and return a shareable preview URL.

This reference is intentionally minimal. The canonical persisted artifact for Phase 8 is still:

- `./translations/[VIDEO_ID]/final/preview.txt`

The file must contain exactly one URL line.

## Endpoint

- Base: `https://filebin.net`
- Upload (PUT): `https://filebin.net/{BIN}/{FILENAME}`

## Upload Final Video

```bash
BIN="[VIDEO_ID]"
FILENAME="final_video.mp4"
FILE="./translations/[VIDEO_ID]/final/final_video.mp4"

curl -sS -X PUT \
  -H "Content-Type: video/mp4" \
  --data-binary "@$FILE" \
  "https://filebin.net/$BIN/$FILENAME"

echo "https://filebin.net/$BIN/$FILENAME" > "./translations/[VIDEO_ID]/final/preview.txt"
```

## Preview URL

After successful upload, the preview/download URL is:

```text
https://filebin.net/{BIN}/{FILENAME}
```

## Verify Upload (Optional)

```bash
curl -I "https://filebin.net/$BIN/$FILENAME"
```

If response includes `HTTP/2 200`, the file is accessible.

## Persist Preview Link

Expected persisted file:

```text
./translations/[VIDEO_ID]/final/preview.txt
```

Content should be a single URL line, e.g.:

```text
https://filebin.net/[VIDEO_ID]/final_video.mp4
```

## Notes

- Filebin links are temporary and intended for quick sharing/preview.
- Use `VIDEO_ID` as `BIN` for deterministic preview path.
- For large video files, keep network retries enabled in your shell environment if needed.
- Do not write extra JSON or commentary into `preview.txt`.
