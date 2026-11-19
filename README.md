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

## Chạy ứng dụng (khuyên dùng: trên máy tính của bạn)

| Bạn muốn | Windows | macOS / Linux |
|---|---|---|
| Dùng trên máy tính | bấm đúp **`run.bat`** | `./run.sh` |
| Mở được từ **điện thoại ở bất cứ đâu** | bấm đúp **`run-public.bat`** | `./run.sh public` |

- Lần đầu chạy sẽ mất 1–2 phút để cài thư viện. Các lần sau mở lên ngay.
- Script tự kiểm tra Python/FFmpeg và báo cách cài nếu thiếu, tự tạo file `.env`, tự mở trình duyệt tại **http://localhost:8000**.
- Tắt app: đóng cửa sổ đen (Windows) hoặc bấm `Ctrl+C`.

### Xuất video nhanh bằng card đồ hoạ
App tự dùng **card đồ hoạ (GPU)** nếu máy có: NVIDIA, Intel (Quick Sync), AMD, hoặc chip Apple trên Mac. Xuất video nhanh hơn 3–10 lần so với dùng CPU. Khi khởi động, cửa sổ đen sẽ in dòng `Bộ mã hoá video: ...` để bạn biết app đang dùng gì. Nếu card lỗi, app tự chuyển sang CPU. Muốn tự chọn thì sửa `VIDEO_ENCODER` trong `.env`.

### Link công khai (mở từ điện thoại)
`run-public.bat` / `./run.sh public` dùng **Cloudflare Tunnel** (miễn phí, không cần tài khoản) để tạo link dạng `https://....trycloudflare.com`:
1. **Bắt buộc** đặt mật khẩu trong `.env`: `APP_PASSWORD=matkhaucuaban`. Script sẽ không chạy nếu thiếu.
2. Chạy script. Lần đầu nó tự tải Cloudflare Tunnel về.
3. Link hiện trong cửa sổ "Link công khai" (Windows) hoặc ngay trên màn hình (macOS/Linux). Mở link trên điện thoại và nhập mật khẩu. Tên đăng nhập gõ gì cũng được.

Lưu ý:
- Link **đổi mỗi lần chạy**.
- Link chỉ hoạt động khi máy tính đang bật và cửa sổ app đang mở.
- Qua link công khai, video tải lên tối đa **95 MB** (giới hạn của Cloudflare miễn phí). Trên máy tính thì không giới hạn.

## Cách khác: chạy trên Hugging Face Spaces

App cần Python + ffmpeg nên **không chạy được trên GitHub Pages**. ⚠️ Hạn mức CPU miễn phí của Hugging Face hiện thường không đủ để chạy (Space sẽ bị *Paused*), nên thường phải mua gói **PRO** (~9 USD/tháng). Bạn **chỉ nhập key ở GitHub**. GitHub Action sẽ tự tạo Space, chép key sang Space và đưa code lên.

**Bước 1. Tạo token Hugging Face**
1. Đăng ký tài khoản tại <https://huggingface.co/join>.
2. Vào <https://huggingface.co/settings/tokens>, bấm **Create new token**, chọn loại **Write** và copy token (dạng `hf_...`).

**Bước 2. Nhập key vào GitHub** (một lần duy nhất)

Vào repo này trên GitHub, chọn **Settings → Secrets and variables → Actions → New repository secret**, rồi thêm lần lượt:

| Name | Secret |
|---|---|
| `HF_TOKEN` | token Hugging Face vừa tạo |
| `GEMINI_API_KEY` | key Gemini (<https://aistudio.google.com/apikey>) |
| `APP_PASSWORD` | mật khẩu vào trang web, do bạn tự đặt |
| `ELEVENLABS_API_KEY` | key ElevenLabs. Không bắt buộc, có thể bỏ qua |

**Bước 3. Chạy**

Vào tab **Actions → Deploy to Hugging Face Space → Run workflow**. Workflow chỉ chạy khi bạn bấm nút này, không tự chạy mỗi lần đẩy code. Đợi khoảng 1 phút cho Action xong (dấu ✅), rồi thêm 3–5 phút để Space build. Sau đó mở:

`https://huggingface.co/spaces/ten-tai-khoan-hugging-face/highlight-ai`

Trình duyệt sẽ hỏi tên đăng nhập (gõ gì cũng được) và mật khẩu (`APP_PASSWORD`).

Muốn cập nhật web sau khi sửa code, chạy lại workflow. Muốn đổi key thì sửa secret trên GitHub rồi chạy lại workflow. Muốn đặt tên Space khác thì thêm **Variable** `HF_SPACE` = `ten-tai-khoan/ten-space`.

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
  media.py      Hàm tiện ích ffmpeg/ffprobe, tự chọn card đồ hoạ để xuất video
static/
  index.html    Giao diện web
```
