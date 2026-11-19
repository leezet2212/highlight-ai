"""Commentary style presets."""

STYLES: dict[str, dict] = {
    "hai_huoc": {
        "label": "😂 Hài hước / tấu hài",
        "prompt": (
            "Bình luận HÀI HƯỚC, tấu hài kiểu streamer Việt. Dùng so sánh bất ngờ, "
            "chơi chữ, meme quen thuộc của game thủ Việt. Pha hay thì khen lố, pha "
            "ngớ ngẩn thì chọc vui. Không thô tục, không xúc phạm."
        ),
        "edge_rate": "+8%",
    },
    "nghiem_tuc": {
        "label": "🎙️ BLV chuyên nghiệp (nghiêm túc)",
        "prompt": (
            "Bình luận NGHIÊM TÚC như bình luận viên giải đấu chuyên nghiệp: phân tích "
            "vị trí, kỹ năng, thời điểm giao tranh, quyết định chiến thuật, dùng đúng "
            "thuật ngữ Liên Quân (farm, gank, combo, bùa, rồng, Tà Thần, trụ...)."
        ),
        "edge_rate": "+5%",
    },
    "hype": {
        "label": "🔥 BLV eSports gào thét",
        "prompt": (
            "Bình luận cực kỳ HÀO HỨNG như BLV chung kết eSports: câu ngắn, dồn dập, "
            "nhiều cảm thán, gào lên ở những pha hạ gục và combo đẹp."
        ),
        "edge_rate": "+15%",
    },
    "ca_khia": {
        "label": "😏 Cà khịa",
        "prompt": (
            "Bình luận kiểu CÀ KHỊA, mỉa mai nhẹ nhàng: châm chọc đồng đội 'báo', đối "
            "thủ 'gà', chính người chơi khi chơi dở. Hài nhưng không độc hại."
        ),
        "edge_rate": "+5%",
    },
    "drama": {
        "label": "😭 Drama / bi kịch",
        "prompt": (
            "Bình luận như phim BI KỊCH, cảm xúc quá đà: mỗi pha chết như một mất mát "
            "lớn lao, mỗi pha thắng như phép màu. Giọng văn sến súa có chủ đích để gây cười."
        ),
        "edge_rate": "-5%",
    },
    "tai_lieu": {
        "label": "🦁 Phim tài liệu thế giới động vật",
        "prompt": (
            "Bình luận như người dẫn PHIM TÀI LIỆU THẾ GIỚI ĐỘNG VẬT: điềm tĩnh, chậm "
            "rãi, mô tả tướng như loài vật trong tự nhiên (săn mồi, bầy đàn, lãnh thổ)."
        ),
        "edge_rate": "-10%",
    },
    "custom": {
        "label": "✍️ Tự viết yêu cầu",
        "prompt": "Bình luận theo đúng yêu cầu riêng của người dùng ở phần ghi chú.",
        "edge_rate": "+0%",
    },
}


# Styles learned from the user's sample videos, keyed "mau_<id>". Loaded and
# saved by the server (data/styles/styles.json).
CUSTOM: dict[str, dict] = {}

PACE_RATE = {"cham": "-5%", "vua": "+5%", "nhanh": "+15%"}


def get_style(key: str) -> dict:
    return STYLES.get(key) or CUSTOM.get(key) or STYLES["hai_huoc"]


def style_prompt(key: str) -> str:
    st = get_style(key)
    text = st["prompt"]
    if st.get("examples"):
        lines = "\n".join(f"- {e}" for e in st["examples"][:5])
        text += ("\nVí dụ câu đúng phong cách này (chỉ để cảm nhận giọng văn – KHÔNG lặp lại "
                 f"nguyên văn, hãy viết câu mới hợp với trận đấu):\n{lines}")
    return text


def edge_rate(key: str) -> str:
    return get_style(key).get("edge_rate", "+0%")


def all_labels() -> dict[str, str]:
    labels = {k: v["label"] for k, v in STYLES.items()}
    labels.update({k: v["label"] for k, v in CUSTOM.items()})
    return labels
