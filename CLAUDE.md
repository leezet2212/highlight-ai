# CLAUDE.md

Hướng dẫn cho Claude (và người) khi đọc/sửa code trong repo này.

## Dự án

**Highlight AI** – web app tự động bình luận video highlight Liên Quân Mobile.
Tải video lên → Gemini xem video và viết lời bình theo phong cách → người dùng sửa → xuất MP4 có giọng đọc + phụ đề cho TikTok/Facebook/YouTube.

Người dùng là người Việt: **mọi chữ hiển thị trên giao diện và mọi thông báo lỗi trả về người dùng đều viết bằng tiếng Việt có dấu**. Tên biến, comment trong code dùng tiếng Anh.

## Chạy & kiểm tra

```bash
pip install -r requirements.txt          # Python 3.10+, cần ffmpeg/ffprobe trong PATH
cp .env.example .env                     # điền GEMINI_API_KEY, ELEVENLABS_API_KEY (không bắt buộc)
python -m uvicorn app.server:app --port 8000 --reload
```

Người dùng cuối chạy **trên máy của họ** (cách chính): `run.bat` / `run.sh`; link công khai qua Cloudflare quick tunnel bằng `run-public.bat` (đặt `HIGHLIGHT_PUBLIC=1` rồi gọi `run.bat`) / `./run.sh public` – bắt buộc có `APP_PASSWORD`, đặt `MAX_UPLOAD_MB=95` vì Cloudflare miễn phí chặn upload >100 MB. Giữ các script đồng bộ khi đổi cách chạy. File `.bat` phải là ASCII không dấu + CRLF, và **không có dấu ngoặc `( )` trong `echo` bên trong khối `if (...)`** (sẽ đóng khối sớm).

**Xuất video**: `media.video_encoders()` dò GPU encoder bằng một lần mã hoá thử (nvenc → qsv → amf → videotoolbox), luôn có `libx264` dự phòng; `render.py` thử lần lượt nếu encoder lỗi. Biến `VIDEO_ENCODER` (auto/tên encoder) và `VIDEO_PRESET` (preset libx264, mặc định veryfast). Thử đường dự phòng bằng cách gán `media._encoder_cache` thành `[('h264_nvenc', ...), media.software_encoder()]` trên máy không có GPU.

**Bản trên web**: `Dockerfile` (cổng `PORT`, mặc định 7860) chạy trên Hugging Face Spaces. `.github/workflows/deploy-hf.yml` (chỉ chạy bằng tay – workflow_dispatch – vì hạn mức Hugging Face miễn phí không đủ, Space của người dùng đang bị Paused) chạy `deploy/deploy_hf.py`: tự tạo Space (mặc định `<tài-khoản-hf>/highlight-ai`, đổi bằng variable `HF_SPACE`), chép các secret GitHub `GEMINI_API_KEY`/`ELEVENLABS_API_KEY`/`APP_PASSWORD` sang secret của Space, rồi upload các file git đang theo dõi (bỏ `deploy/`, `.github/`, `CLAUDE.md`; header YAML của Space ở `deploy/hf-header.md`). Không có secret `HF_TOKEN` thì bỏ qua. Biến môi trường khi chạy trên web: `APP_PASSWORD` (HTTP Basic auth, `/healthz` không cần mật khẩu), `JOB_TTL_HOURS` (tự xoá job cũ), `MAX_CONCURRENT_RENDERS` (semaphore giới hạn số video xuất cùng lúc), `DATA_DIR`.

**Test tự động** (không cần key/Internet, Gemini được thay bằng hàm giả, giọng dùng provider `_test`): `pip install pytest && python -m pytest -q`. Chạy trước mỗi lần push và thêm test khi thêm chức năng. Ngoài ra kiểm tra thủ công:

- **Phần ghép video (không cần key, không cần mạng)**: tạo video giả rồi gọi `render.render(...)` với `provider="_test"` (giọng giả bằng sóng sine, chỉ dành cho kiểm thử, không hiện trên giao diện):
  ```bash
  ffmpeg -y -f lavfi -i testsrc2=size=1280x720:rate=30:duration=12 -f lavfi -i sine=duration=12 -c:v libx264 -c:a aac -shortest /tmp/src.mp4
  ```
  Thử đủ các trường hợp: video ngang/dọc, có/không có tiếng, video có cờ xoay (`-display_rotation 90`), các khung `9:16`, `16:9`, `1:1`, `original`. Trích 1 khung hình (`ffmpeg -ss 5 -i output.mp4 -frames:v 1 x.png`) để xem bố cục và phụ đề.
- **API**: `POST /api/jobs/{id}/render` với `"provider": "_test"` chạy được cả luồng mà không cần key.
- **Giao diện**: mở http://localhost:8000 ở kích thước điện thoại (đa số người dùng xem trên điện thoại), kiểm tra không có lỗi console.
- Gemini, ElevenLabs và Edge TTS cần key/Internet thật – nói rõ với người dùng nếu chưa thử được phần này.

## Kiến trúc

```
app/server.py     FastAPI: API + phục vụ static/. Job chạy nền bằng thread.
app/script_ai.py  Gửi video cho Gemini → JSON {summary, segments[start,end,event,text], posts{tiktok,facebook,youtube}{title,caption,hashtags}}; normalize() kẹp thời gian, bỏ chồng lấn; normalize_posts() làm sạch hashtag (luôn có #Shorts cho YouTube); generate_posts() viết lại caption chỉ từ chữ (không gửi video); gemini_error_message() dịch lỗi Gemini sang tiếng Việt.
app/styles.py     Danh sách phong cách bình luận (label, prompt, tốc độ đọc Edge).
app/tts.py        ElevenLabs (REST qua httpx) và Edge TTS; provider "_test" cho kiểm thử. Bộ nhớ đệm giọng `synthesize_cached()` (khoá = provider+voice+model+tốc độ+chữ) ở `data/tts_cache/`, dùng chung cho nghe thử (`POST /api/tts-preview`) và xuất video – nghe thử rồi xuất không tốn ElevenLabs hai lần. Giữ tốc độ đọc giống nhau ở hai chỗ (`edge_rate(style)`) để trúng cache.
app/render.py     Toàn bộ khâu dựng video bằng ffmpeg.
app/media.py      ffprobe/ffmpeg helpers: probe(), audio_duration(), make_preview(), run(), video_encoders().
static/index.html Giao diện một trang, JS thuần, không build step.
Dockerfile        Image chạy trên web (Hugging Face Spaces).
deploy/           deploy_hf.py (tạo Space, chép secret, upload) + hf-header.md; chạy bởi .github/workflows/deploy-hf.yml.
tests/            test_app.py – pytest, chạy offline.
data/jobs/<id>/   Dữ liệu từng video (gitignored): source.*, preview.mp4, job.json, voice/, voice.wav, subs.ass, output.mp4, output.srt
```

### Luồng một job
1. `POST /api/upload` → lưu `source.*`, `probe()`, tạo `preview.mp4` (≤960px, nhẹ) dùng cho trình phát trên web **và gửi cho Gemini** (đỡ tốn hạn mức miễn phí).
2. `POST /api/jobs/{id}/script` → `script_ai.generate_script()` chạy nền.
3. Giao diện hỏi `GET /api/jobs/{id}` mỗi 1,5 giây (`status`: idle/running/done/error, `task`, `progress`, `error`).
4. (tuỳ chọn) `POST /api/jobs/{id}/captions` → `generate_posts()` chạy nền, cập nhật `script.posts`.
5. `POST /api/jobs/{id}/render` → `render.render()` chạy nền → `output.mp4` + `output.srt` (giữ nguyên `script.posts`).

Giao diện: mỗi tác vụ nền (`script`/`render`/`captions`) hiện tiến độ và lỗi ở vùng riêng – bảng `AREAS` trong `index.html`; thêm tác vụ mới thì thêm vào đó. Caption người dùng sửa chỉ nằm ở trình duyệt (không lưu lên máy chủ).

Trạng thái job nằm trong dict `JOBS` (bộ nhớ) và được ghi ra `job.json`; `restore_jobs()` nạp lại khi khởi động lại máy chủ. Mỗi job chỉ chạy một tác vụ một lúc (trả 409 nếu đang bận).

### render.py – những điểm dễ làm hỏng
- **Bố cục** (`layout()`): video luôn được giữ **trọn vẹn**, không bao giờ cắt. Nếu khác tỉ lệ khung xuất, video được thu vừa khung và nền là bản phóng to + làm mờ của chính video (làm mờ ở 1/4 độ phân giải cho nhanh). Đây là yêu cầu chính của người dùng: video Liên Quân quay ngang xuất 9:16 vẫn xem được hết màn hình game.
- **Phụ đề** (`write_ass()`): nếu dải trống dưới video đủ cao thì phụ đề nằm trong dải đó (không che HUD game), không thì ở đáy khung. Tiêu đề nằm ở dải trên. Phụ đề được cắt thành cụm ngắn (6 từ khi khung dọc, 9 từ khi ngang). Font lấy từ `SUBTITLE_FONT` – phải hỗ trợ tiếng Việt.
- Lệnh ffmpeg cuối chạy với `cwd=job_dir` và tham chiếu `subs.ass`/`voice.wav` bằng tên tương đối, để tránh phải escape đường dẫn trong filter `ass=` (đường dẫn Windows có `:` và `\`). Giữ nguyên cách này.
- **Canh thời gian giọng**: câu dài hơn chỗ trống được tăng tốc tối đa `MAX_SPEEDUP` (1.35×); vẫn dài thì đẩy câu sau lùi lại – giọng không bao giờ chồng nhau. Câu cuối dài được phép giữ khung hình cuối thêm tối đa `MAX_TAIL` giây (`tpad`).
- **Âm thanh**: `mute_original=True` bỏ hẳn luồng `[0:a]` (coi như video không có tiếng). Ngược lại tiếng game × `game_volume`, `sidechaincompress` để tự giảm tiếng game khi có giọng (`duck`), rồi `amix` + `alimiter`. Phải xử lý cả video không có luồng âm thanh (`info.has_audio`).
- **Giọng từng câu**: segment có thể mang `provider` + `voice_id` riêng (`normalize()` giữ lại khi có đủ cả hai); `render.line_voice_of()` dùng giọng riêng nếu provider hợp lệ, không thì giọng chung. Nghe thử (`say()` trong index.html) cũng ưu tiên giọng riêng của câu.
- **Hình ảnh** (`build_video_filter()`): thứ tự cố định: che vùng (`blur_boxes`, toạ độ 0..1 của khung **nguồn**, tối đa 10, boxblur bán kính ≤ w/4 vì kênh màu chỉ bằng nửa) → làm nét (`enhance`: hqdn3d trước, scale lanczos, unsharp sau) → đặt vào khung xuất → logo (input số 2, `colorchannelmixer` cho độ trong) → `tpad` → `ass` (phụ đề, tiêu đề, chữ ký chữ style `Mark`) → yuv420p. Logo và chữ ký dùng chung góc (`mark_position()`): logo sát góc, chữ ký ngay dưới/trên logo. Logo lưu một file dùng chung `data/assets/logo.png` (`/api/logo` GET/POST/DELETE, chuẩn hoá về PNG ≤800px). `blur_boxes` được lưu vào job khi xuất để nạp lại sau khi tải lại trang; chữ ký/làm nét lưu ở `localStorage` (`hlPrefs`). Không làm chức năng xoá watermark của người khác.
- `probe()` trả kích thước **sau khi xoay** (đọc rotation trong side data/tags) vì ffmpeg tự xoay khi giải mã.

### Gemini (script_ai.py)
- SDK `google-genai`: `client.files.upload(file=...)`, chờ hết trạng thái PROCESSING, `generate_content` với `response_schema=Script` (pydantic) và `response_mime_type="application/json"`, xong thì xoá file đã tải lên.
- Model lấy từ `GEMINI_MODEL` (mặc định `gemini-2.5-flash`).
- Prompt yêu cầu ~3 từ tiếng Việt/giây, các đoạn không chồng nhau, có câu mồi ở đầu và câu chốt ở cuối. Giao diện dùng cùng quy tắc 3 từ/giây để cảnh báo "hơi dài" – nếu đổi thì đổi cả hai chỗ.

## Việc hay gặp

- **Thêm phong cách bình luận**: chỉ thêm một mục vào `STYLES` trong `app/styles.py` (`label`, `prompt`, `edge_rate`). Giao diện tự hiện.
- **Phong cách học từ video mẫu**: `POST /api/style-samples` (video có tiếng, ≤5 phút) → thread nền `script_ai.analyze_style()` (Gemini nghe video, trả `StyleProfile`; `normalize_profile()` báo lỗi nếu không có giọng bình luận) → lưu `styles.CUSTOM["mau_<id>"]` vào `data/styles/styles.json` (không bị TTL xoá), video mẫu xoá ngay. Tiến độ ở `SAMPLE_TASKS` (bộ nhớ), hỏi bằng `GET /api/style-samples/{id}`. Sửa/xoá: `PUT`/`DELETE /api/styles/{key}` (chỉ phong cách đã học). Luôn đi qua `styles.get_style()` / `style_prompt()` / `edge_rate()` / `all_labels()` thay vì đọc `STYLES` trực tiếp, để phong cách đã học dùng được ở mọi chỗ. `style_prompt()` thêm câu ví dụ kèm dặn không chép nguyên văn. Chỉ học cách viết lời bình – không làm nhái giọng nói người thật.
- **Thêm khung hình xuất**: thêm vào `frame_size()` trong `render.py` và thêm một ô chọn `name="aspect"` trong `index.html`.
- **Thêm nhà cung cấp giọng**: thêm hàm `synth_xxx()` và nhánh trong `synthesize()` + `list_voices()` ở `tts.py`, thêm `<option>` trong `#provider` ở `index.html`.
- **Đổi giao diện**: tất cả nằm trong `static/index.html` (CSS biến ở `:root`, JS ở cuối file). Không thêm framework/bước build.
- **Responsive** (khối `/* responsive */` cuối CSS): `min-width:0` cho con của grid/flex (nếu thiếu, một `<select>` tên giọng dài làm tràn ngang cả trang trên điện thoại 320px); `@media (pointer: coarse)` nút ≥ 42–44px và chữ ô nhập 16px (iOS không tự phóng to); ≤820px trình chỉnh sửa 1 cột, video ≤42vh; ≤520px bố cục điện thoại; điện thoại xoay ngang (max-height 520px) giữ 2 cột video|kịch bản; ≥1400px rộng hơn. Khi sửa giao diện, kiểm tra không tràn ngang ở 320, 390, 844×390, 768, 1024, 1440, 1920 (`document.documentElement.scrollWidth <= clientWidth`).

## Quy ước

- Không commit `.env`, `data/`, file zip hay video thử.
- Lỗi do người dùng/dịch vụ ngoài → ném exception có thông báo tiếng Việt dễ hiểu (gợi ý cách sửa); `server.background()` đưa nó lên giao diện.
- Lưu ý pháp lý cần giữ trong README/giao diện: gói miễn phí ElevenLabs không cho dùng thương mại; gói miễn phí Gemini có thể dùng dữ liệu để cải thiện sản phẩm.
