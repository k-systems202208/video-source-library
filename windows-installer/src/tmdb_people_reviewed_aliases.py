from __future__ import annotations

# Human-reviewed aliases derived from the real-library people audit.
#
# Safety rule:
# These aliases are never used as global TMDb search terms.  They are compared
# only with the name/original_name of people who already appear in the matched
# work's TMDb credits, and a match is accepted only when exactly one person id
# remains.
REVIEWED_PERSON_CREDIT_ALIASES: dict[str, tuple[str, ...]] = {
    "千紗": ("CHISA",),
    "サイモン・キャロウ": ("Simon Callow",),
    "ジョン・トラボルタ": ("ジョン・トラヴォルタ", "John Travolta"),
    "ウィリアム・サドラー": ("William Sadler",),
    "ジェマ・ジョーンズ": ("Gemma Jones",),
    "ジョー・ヴィテレリ": ("Joe Viterelli",),
    "ユ・ジテ": ("유지태",),
    "カン・ヘジョン": ("강혜정",),
    "キム・ビョンオク": ("김병옥",),
    "ニッキー・ブロンスキー": ("Nikki Blonsky",),
    "カム・ジガンデイ": ("キャム・ギガンデット", "Cam Gigandet"),
    "クロティルド・モレ": ("Clotilde Mollet",),
    "F・マーレイ・エイブラハム": ("F・マーリー・エイブラハム", "F. Murray Abraham"),
    "アンダーズ・ホーム": ("アンダース・ホルム", "Anders Holm"),
    "ブレット・カレン": ("Brett Cullen",),
    "リンダ・メイ": ("Linda May",),
    "スワンキー": ("Swankie",),
    "ボブ・ウェルズ": ("Bob Wells",),
    "トルーマン・ハンクス": ("Truman Hanks",),
    "キリアン・マーフィー": ("キリアン・マーフィ", "Cillian Murphy"),
    "ジェイデン・マーテル": ("ジェイデン・リーバハー", "Jaeden Martell", "Jaeden Lieberher"),
    "セイディ・ソヴラル": ("Sadie Soverall",),
    "ニコラス・ガリツィン": ("ニコラス・ガリツィ", "Nicholas Galitzine"),
    "増田康好": ("Yasuyoshi Masuda",),
    "渡辺千秋": ("Chiaki Watanabe",),
    "小原裕貴": ("Yuki Kohara",),
    "藤井萩花": ("Fujii Shuuka", "Shuuka Fujii", "Shuka Fujii"),
}
