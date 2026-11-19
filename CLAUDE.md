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

Người dùng cuối chạy bằng `run.bat` (Windows) / `run.sh` (macOS/Linux) – giữ hai file này đồng bộ khi đổi cách chạy.

**Bản trên web**: `Dockerfile` (cổng `PORT`, mặc định 7860) chạy trên Hugging Face Spaces. `.github/workflows/deploy-hf.yml` đẩy repo sang Space mỗi khi có push lên `main` (cần secret `HF_TOKEN` + variable `HF_SPACE` trên GitHub; header YAML của Space nằm ở `deploy/hf-header.md`). Mọi thứ trên `main` sẽ lên web ngay – kiểm tra kỹ trước khi push. Biến môi trường khi chạy trên web: `APP_PASSWORD` (HTTP Basic auth, `/healthz` không cần mật khẩu), `JOB_TTL_HOURS` (tự xoá job cũ), `MAX_CONCURRENT_RENDERS` (semaphore giới hạn số video xuất cùng lúc), `DATA_DIR`.

Chưa có bộ test tự động. Kiểm tra khi sửa:

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
app/script_ai.py  Gửi video cho Gemini → JSON {summary, segments[start,end,event,text]}; normalize() kẹp thời gian, bỏ chồng lấn.
app/styles.py     Danh sách phong cách bình luận (label, prompt, tốc độ đọc Edge).
app/tts.py        ElevenLabs (REST qua httpx) và Edge TTS; provider "_test" cho kiểm thử.
app/render.py     Toàn bộ khâu dựng video bằng ffmpeg.
app/media.py      ffprobe/ffmpeg helpers: probe(), audio_duration(), make_preview(), run().
static/index.html Giao diện một trang, JS thuần, không build step.
Dockerfile        Image chạy trên web (Hugging Face Spaces).
deploy/           Header YAML cho Space; .github/workflows/deploy-hf.yml tự deploy.
data/jobs/<id>/   Dữ liệu từng video (gitignored): source.*, preview.mp4, job.json, voice/, voice.wav, subs.ass, output.mp4, output.srt
```

### Luồng một job
1. `POST /api/upload` → lưu `source.*`, `probe()`, tạo `preview.mp4` (≤960px, nhẹ) dùng cho trình phát trên web **và gửi cho Gemini** (đỡ tốn hạn mức miễn phí).
2. `POST /api/jobs/{id}/script` → `script_ai.generate_script()` chạy nền.
3. Giao diện hỏi `GET /api/jobs/{id}` mỗi 1,5 giây (`status`: idle/running/done/error, `task`, `progress`, `error`).
4. `POST /api/jobs/{id}/render` → `render.render()` chạy nền → `output.mp4` + `output.srt`.

Trạng thái job nằm trong dict `JOBS` (bộ nhớ) và được ghi ra `job.json`; `restore_jobs()` nạp lại khi khởi động lại máy chủ. Mỗi job chỉ chạy một tác vụ một lúc (trả 409 nếu đang bận).

### render.py – những điểm dễ làm hỏng
- **Bố cục** (`layout()`): video luôn được giữ **trọn vẹn**, không bao giờ cắt. Nếu khác tỉ lệ khung xuất, video được thu vừa khung và nền là bản phóng to + làm mờ của chính video (làm mờ ở 1/4 độ phân giải cho nhanh). Đây là yêu cầu chính của người dùng: video Liên Quân quay ngang xuất 9:16 vẫn xem được hết màn hình game.
- **Phụ đề** (`write_ass()`): nếu dải trống dưới video đủ cao thì phụ đề nằm trong dải đó (không che HUD game), không thì ở đáy khung. Tiêu đề nằm ở dải trên. Phụ đề được cắt thành cụm ngắn (6 từ khi khung dọc, 9 từ khi ngang). Font lấy từ `SUBTITLE_FONT` – phải hỗ trợ tiếng Việt.
- Lệnh ffmpeg cuối chạy với `cwd=job_dir` và tham chiếu `subs.ass`/`voice.wav` bằng tên tương đối, để tránh phải escape đường dẫn trong filter `ass=` (đường dẫn Windows có `:` và `\`). Giữ nguyên cách này.
- **Canh thời gian giọng**: câu dài hơn chỗ trống được tăng tốc tối đa `MAX_SPEEDUP` (1.35×); vẫn dài thì đẩy câu sau lùi lại – giọng không bao giờ chồng nhau. Câu cuối dài được phép giữ khung hình cuối thêm tối đa `MAX_TAIL` giây (`tpad`).
- **Âm thanh**: tiếng game × `game_volume`, `sidechaincompress` để tự giảm tiếng game khi có giọng (`duck`), rồi `amix` + `alimiter`. Phải xử lý cả video không có luồng âm thanh (`info.has_audio`).
- `probe()` trả kích thước **sau khi xoay** (đọc rotation trong side data/tags) vì ffmpeg tự xoay khi giải mã.

### Gemini (script_ai.py)
- SDK `google-genai`: `client.files.upload(file=...)`, chờ hết trạng thái PROCESSING, `generate_content` với `response_schema=Script` (pydantic) và `response_mime_type="application/json"`, xong thì xoá file đã tải lên.
- Model lấy từ `GEMINI_MODEL` (mặc định `gemini-2.5-flash`).
- Prompt yêu cầu ~3 từ tiếng Việt/giây, các đoạn không chồng nhau, có câu mồi ở đầu và câu chốt ở cuối. Giao diện dùng cùng quy tắc 3 từ/giây để cảnh báo "hơi dài" – nếu đổi thì đổi cả hai chỗ.

## Việc hay gặp

- **Thêm phong cách bình luận**: chỉ thêm một mục vào `STYLES` trong `app/styles.py` (`label`, `prompt`, `edge_rate`). Giao diện tự hiện.
- **Thêm khung hình xuất**: thêm vào `frame_size()` trong `render.py` và thêm một ô chọn `name="aspect"` trong `index.html`.
- **Thêm nhà cung cấp giọng**: thêm hàm `synth_xxx()` và nhánh trong `synthesize()` + `list_voices()` ở `tts.py`, thêm `<option>` trong `#provider` ở `index.html`.
- **Đổi giao diện**: tất cả nằm trong `static/index.html` (CSS biến ở `:root`, JS ở cuối file). Không thêm framework/bước build.

## Quy ước

- Không commit `.env`, `data/`, file zip hay video thử.
- Lỗi do người dùng/dịch vụ ngoài → ném exception có thông báo tiếng Việt dễ hiểu (gợi ý cách sửa); `server.background()` đưa nó lên giao diện.
- Lưu ý pháp lý cần giữ trong README/giao diện: gói miễn phí ElevenLabs không cho dùng thương mại; gói miễn phí Gemini có thể dùng dữ liệu để cải thiện sản phẩm.
