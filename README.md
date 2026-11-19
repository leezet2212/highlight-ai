# 🎮 Highlight AI – Bình luận Liên Quân bằng AI

Tải video highlight (chưa có tiếng bình luận) lên → AI **xem trận đấu** và viết lời bình theo phong cách bạn chọn → bạn sửa lại nếu muốn → xuất **video có giọng đọc + phụ đề** để đăng TikTok, Facebook, YouTube.

## Tính năng

- 🤖 **AI xem video thật** (Google Gemini, miễn phí) và viết lời bình bám theo từng mốc thời gian.
- 🎭 **7 phong cách**: Hài hước, BLV nghiêm túc, BLV eSports gào thét, Cà khịa, Drama, Phim tài liệu động vật, hoặc tự viết yêu cầu.
- ✍️ **Sửa kịch bản** trước khi xuất: đổi lời, chỉnh thời gian, thêm/xoá câu, bấm ▶ để xem đúng đoạn đó.
- 🗣️ **Giọng đọc**: ElevenLabs (cảm xúc, có gói miễn phí) hoặc Edge TTS (miễn phí hoàn toàn).
- 🔉 **Tự giảm tiếng game** khi đang bình luận, chỉnh được âm lượng game và giọng.
- 📱 **Xuất nhiều khung hình**:
  - **Dọc 9:16** (TikTok, Reels, Shorts): video ngang được **giữ trọn màn hình game**, phía trên và dưới là nền mờ. Phụ đề nằm ở vùng trống bên dưới nên không che giao diện game, tiêu đề nằm ở trên.
  - **Ngang 16:9** (YouTube, Facebook): xem toàn màn hình khi xoay ngang điện thoại. Video dọc sẽ được làm mờ hai bên.
  - **Vuông 1:1** hoặc **giữ nguyên** khung gốc.
- 🔄 Video quay bằng điện thoại có cờ xoay được tự xoay đúng chiều.
- 📝 Tải kèm file phụ đề `.srt` để đăng lên YouTube.

## Cài đặt (một lần)

1. **Python 3.10 trở lên**: tải tại <https://www.python.org/downloads/>. Trên Windows, nhớ tick ô *"Add Python to PATH"* khi cài.
2. **FFmpeg**:
   - Windows: mở PowerShell và chạy `winget install Gyan.FFmpeg`
   - macOS: `brew install ffmpeg`
   - Ubuntu: `sudo apt install ffmpeg`
3. **Lấy key**:
   - **Gemini** (miễn phí): <https://aistudio.google.com/apikey>, đăng nhập Google và bấm *Create API key*.
   - **ElevenLabs** (không bắt buộc): <https://elevenlabs.io/app/settings/api-keys>
4. Copy file `.env.example` thành `.env` rồi dán key vào:
   ```
   GEMINI_API_KEY=key-gemini-cua-ban
   ELEVENLABS_API_KEY=key-elevenlabs-cua-ban
   ```

## Chạy ứng dụng

- **Windows**: bấm đúp `run.bat`
- **macOS/Linux**: chạy `./run.sh`

Sau đó mở trình duyệt tại **http://localhost:8000**.

## Đưa lên web (Hugging Face Spaces – miễn phí)

App cần Python + ffmpeg nên **không chạy được trên GitHub Pages**. Hugging Face Spaces miễn phí, có 2 CPU và 16 GB RAM, đủ để dựng video. Repo đã có sẵn `Dockerfile` và GitHub Action tự đẩy code sang Space.

**Bước 1. Tạo Space**
1. Đăng ký tài khoản tại <https://huggingface.co/join>.
2. Vào <https://huggingface.co/new-space>, đặt tên `highlight-ai`, chọn **Docker → Blank**, để **Public**, rồi bấm *Create Space*.
3. Trong Space, vào **Settings → Variables and secrets** và thêm các **Secret**:
   - `GEMINI_API_KEY`
   - `ELEVENLABS_API_KEY` (không bắt buộc)
   - `APP_PASSWORD`: mật khẩu vào trang. **Bắt buộc nên có**, nếu không ai có link cũng dùng hết lượt miễn phí của bạn.

**Bước 2. Cho GitHub tự đẩy code sang Space**
1. Tạo token tại <https://huggingface.co/settings/tokens>, chọn quyền **Write**.
2. Trong repo GitHub, vào **Settings → Secrets and variables → Actions**:
   - Tab *Secrets*, thêm `HF_TOKEN` = token vừa tạo.
   - Tab *Variables*, thêm `HF_SPACE` = `ten-hugging-face-cua-ban/highlight-ai`.
3. Đẩy code lên nhánh `master` (hoặc vào tab **Actions → Deploy to Hugging Face Space → Run workflow**).
4. Đợi Space build xong, khoảng 3–5 phút, rồi mở `https://huggingface.co/spaces/ten-cua-ban/highlight-ai`. Trình duyệt sẽ hỏi tên đăng nhập (gõ gì cũng được) và mật khẩu (`APP_PASSWORD`).

Từ đó, mỗi lần sửa code và đẩy lên `master`, web sẽ tự cập nhật.

**Lưu ý khi chạy trên web:** Space miễn phí sẽ "ngủ" nếu 48 giờ không ai dùng (mở lại sẽ tự chạy, mất khoảng 1 phút). Video trên máy chủ bị xoá khi Space khởi động lại và tự xoá sau 24 giờ (`JOB_TTL_HOURS`), nên nhớ tải video về ngay. Mỗi lần chỉ xuất 1 video, người sau sẽ tự xếp hàng chờ.

Dịch vụ khác (Render, Railway, Fly.io, VPS) cũng chạy được bằng `Dockerfile` này. Ứng dụng đọc cổng mạng từ biến `PORT`, và cần ít nhất 1–2 GB RAM.

## Cách dùng

1. Kéo thả video highlight vào trang.
2. Chọn phong cách. Bạn có thể ghi thêm yêu cầu, ví dụ *"mình cầm Nakroth áo đỏ, gọi mình là anh Tèo, giọng miền Tây"*.
3. Bấm **🤖 AI xem trận & viết lời bình** và đợi khoảng 30–60 giây.
4. Đọc lại kịch bản và sửa cho hợp ý. Câu nào có cảnh báo *"hơi dài"* thì nên rút gọn.
5. Chọn khung hình, giọng đọc, tiêu đề rồi bấm **🎬 Xuất video**.
6. Tải video MP4 về và đăng lên mạng xã hội.

## Lưu ý

- **Gemini miễn phí** có giới hạn số lượt mỗi ngày. Ở gói miễn phí, Google có thể dùng dữ liệu gửi lên để cải thiện sản phẩm.
- **ElevenLabs miễn phí** cho khoảng 10.000 ký tự mỗi tháng, **không được dùng thương mại** và cần ghi nguồn. Nếu kênh bật kiếm tiền, hãy nâng lên gói Starter hoặc dùng giọng Edge.
- Edge TTS cần có Internet.
- Nên dùng video trận đấu của chính bạn, và tắt nhạc nền game khi quay để tránh bị báo bản quyền.
- Video tải lên và kết quả được lưu trong thư mục `data/`. Bạn có thể xoá thư mục này bất cứ lúc nào.

## Cấu trúc mã

```
app/
  server.py     Máy chủ web (FastAPI) + API
  script_ai.py  Gửi video cho Gemini, nhận kịch bản theo mốc thời gian
  styles.py     Các phong cách bình luận (sửa/thêm phong cách ở đây)
  tts.py        Giọng đọc ElevenLabs / Edge TTS
  render.py     Ghép giọng, giảm tiếng game, phụ đề, khung 9:16/16:9 nền mờ
  media.py      Hàm tiện ích ffmpeg/ffprobe
static/
  index.html    Giao diện web
```
