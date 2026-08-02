"""Apply newline normalization to translations.json and fix a handful of
entries whose placeholders / highlight tags were corrupted by the original
machine translation pass.

Run:  python3 fix_translations.py [--out translations.json]
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from common import bootstrap

bootstrap()

from normalize_newlines import realign

# Manual fixes: (file, english_source) -> corrected Vietnamese.
# The English source keys are the exact strings stored in translations.json.
MANUAL_FIXES = {
    ("text.msg",
     "Activations +{1}\nReady for reactivation after {2} sec."): (
        "Số lần kích hoạt +{1}\nSẵn sàng tái kích hoạt sau {2} giây"
    ),
    ("text.msg",
     "Activations +{1}\nReady for reactivation after {2} seconds"): (
        "Số lần kích hoạt +{1}\nSẵn sàng tái kích hoạt sau {2} giây"
    ),
    ("text.msg",
     "DMG Taken from Debuffs -{0}%\nDebuff Duration -{1}%\n"
     "Movement Restriction -{0}%"): (
        "S.THƯƠNG nhận từ trạng thái bất lợi -{0}%\n"
        "Thời gian hiệu ứng bất lợi -{1}%\n"
        "Hạn chế di chuyển -{0}%"
    ),
    ("text.msg", "Trait Lvl +{0}"): "Cấp Đặc Tính +{0}",
    ("text.msg",
     "When at {4:.1f} max HP or less:\nATK +{0:.1f}% / DMG Cap +{1:.1f}%"): (
        "Khi HP tối đa bằng hoặc thấp hơn {4:.1f}:\n"
        "Tấn Công +{0:.1f}% / giới hạn S.THƯƠNG +{1:.1f}%"
    ),
    ("text.msg",
     "ATK +{0:.1f}% / DMG Cap +{1:.1f}%\n"
     "If equipped weapon is transcended:\n"
     "ATK +{5:.1f}% / DMG Cap +{6:.1f}%"): (
        "Tấn Công +{0:.1f}% / giới hạn S.THƯƠNG +{1:.1f}%\n"
        "Nếu vũ khí đang trang bị được siêu việt:\n"
        "Tấn Công +{5:.1f}% / giới hạn S.THƯƠNG +{6:.1f}%"
    ),
    ("text.msg",
     "Grants Debuff Immunity for {0} sec. to the entire party\n"
     "Realm of Ice: Also grants DMG\u2191 \n"
     "({4}% to Katalina / {2}% to allies) for {3} sec."): (
        "Ban Miễn Trạng Thái Bất Lợi cho toàn đội trong {0} giây\n"
        "Cõi Băng Tuyết: Đồng thời ban S.THƯƠNG Cường Hóa \n"
        "({4}% cho Katalina / {2}% cho đồng đội) trong {3} giây."
    ),
    ("text_ui.msg", "<d>{0}<d> requests to kick a player."): (
        "<d>{0}<d> yêu cầu đuổi một người chơi."
    ),
    ("text_ui.msg",
     "You have a request to remove <d>{:s}<d> from the party.\n"
     "Do you want to remove them?"): (
        "Bạn nhận được yêu cầu đuổi <d>{:s}<d> khỏi tổ đội.\n"
        "Bạn có muốn đuổi họ không?"
    ),
    ("text_ui.msg",
     "Matchmaking Method must be set to Open to use tickets."): (
        "Chế độ ghép trận phải được đặt thành Công Khai để sử dụng vé."
    ),
}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "translations.json"
    with open(out, encoding="utf-8") as f:
        data = json.load(f)

    shutil.copy(out, out + ".bak")
    tr = data["translations"]

    stats = {"realigned": 0, "split_only": 0, "manual": 0, "skipped": 0}
    for f, d in tr.items():
        for en, vn in list(d.items()):
            key = (f, en)
            if key in MANUAL_FIXES:
                new_vn = MANUAL_FIXES[key]
                stats["manual"] += 1
            else:
                new_vn, changed = realign(en, vn)
                if not changed:
                    stats["skipped"] += 1
                    continue
                if en.count("\n") != vn.count("\n"):
                    stats["realigned"] += 1
                else:
                    stats["split_only"] += 1
            d[en] = new_vn

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print("done:", stats)
    print("backup:", out + ".bak")


if __name__ == "__main__":
    main()
