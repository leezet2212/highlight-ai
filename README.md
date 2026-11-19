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
