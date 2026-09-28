/**
 * Vietnamese names and meanings for the eleven grading labels and the
 * segmented anatomy, plus the reference card shown in the viewer.
 *
 * ## Display only
 *
 * Nothing here changes a stored value. A cell still holds "Moderate" or
 * "Grade II", because that exact string is what correction_log records and
 * what backend/app/feedback/build_dataset.py maps back to a class index --
 * translating the value would make every Vietnamese correction an unknown
 * severity that re-training silently drops. Only what is *shown* changes.
 *
 * ## Where each definition comes from
 *
 * SpineNet labels: SpineNetV2 (Windsor et al., arXiv 2205.01683), Section 4.3,
 * p. 14, checked against the network in backend/spinenet/models/grading.py and
 * the label formatting in backend/spinenet/utils/gt_formatting.py. Where the
 * two disagree the code wins, because the code is what produced the weights,
 * and the disagreement is stated on the card rather than smoothed over:
 *   - the paper calls spondylolisthesis binary; the head has three outputs and
 *     training labels were clipped with `label > 1 -> 2`, so the last class is
 *     "grade II or worse", not "grade II";
 *   - marrow changes are binary, built by OR-ing Modic type 1, 2, 3 and mixed.
 * Pfirrmann's five grades follow Pfirrmann et al., Spine 2001, which the paper
 * cites for the scale; the paper itself fixes only the endpoints.
 * Canal and foraminal stenosis: the app's own CBAM model, trained on the RSNA
 * 2024 labels, whose scale merges normal and mild into one class.
 */

import { CONDITION_SEVERITIES } from "./severityVocabulary";
import type { Lang } from "./i18n";

/**
 * `short` is what a table cell shows when `vi` does not fit a dropdown. The
 * reference card always uses `vi`, so the abbreviation is spelled out where
 * the scale is explained.
 */
export type Level = { value: string; vi: string; short?: string; meaning: string };

export type ConditionInfo = {
  /** Short Vietnamese header for the grade table. */
  short: string;
  /** Full Vietnamese name for the reference card. */
  full: string;
  /** English as the table showed it before, kept as the secondary line. */
  en: string;
  source: "CBAM" | "SpineNet";
  definition: string;
  levels: Level[];
  /** What the reader should not assume, stated where they read the scale. */
  caveat?: string;
};

const CBAM_LEVELS: Level[] = [
  { value: "Normal/Mild", vi: "Bình thường / Nhẹ", short: "BT / Nhẹ", meaning: "Không hẹp hoặc hẹp nhẹ. Bộ RSNA 2024 gộp hai mức này làm một." },
  { value: "Moderate", vi: "Vừa", meaning: "Hẹp mức độ vừa." },
  { value: "Severe", vi: "Nặng", meaning: "Hẹp nặng." },
];

const BINARY = (present: string, absent = "Không có dấu hiệu."): Level[] => [
  { value: "Absent", vi: "Không có", meaning: absent },
  { value: "Present", vi: "Có", meaning: present },
];

export const CONDITIONS: Record<string, ConditionInfo> = {
  canal_stenosis: {
    short: "Hẹp ống sống",
    full: "Hẹp ống sống trung tâm",
    en: "Canal",
    source: "CBAM",
    definition: "Ống sống trung tâm bị hẹp lại, có thể chèn ép tuỷ và các rễ thần kinh.",
    levels: CBAM_LEVELS,
  },
  left_foraminal: {
    short: "Hẹp lỗ LH trái",
    full: "Hẹp lỗ liên hợp bên trái",
    en: "L. foraminal",
    source: "CBAM",
    definition: "Lỗ liên hợp — nơi rễ thần kinh đi ra khỏi ống sống — bị hẹp. Trường hợp nặng có thể chèn ép rễ thần kinh.",
    levels: CBAM_LEVELS,
  },
  right_foraminal: {
    short: "Hẹp lỗ LH phải",
    full: "Hẹp lỗ liên hợp bên phải",
    en: "R. foraminal",
    source: "CBAM",
    definition: "Như bên trái, ở lỗ liên hợp bên phải.",
    levels: CBAM_LEVELS,
  },
  pfirrmann: {
    short: "Pfirrmann",
    full: "Thoái hoá đĩa đệm (thang Pfirrmann)",
    en: "Pfirrmann",
    source: "SpineNet",
    definition: "Mức thoái hoá đĩa đệm trên ảnh T2, từ độ 1 (không thoái hoá) tới độ 5 (thoái hoá nặng).",
    levels: [
      { value: "Grade 1", vi: "Độ 1", meaning: "Đĩa đồng nhất, tín hiệu sáng; chiều cao bình thường." },
      { value: "Grade 2", vi: "Độ 2", meaning: "Không đồng nhất, có thể có dải ngang; nhân và vòng xơ vẫn phân biệt rõ; chiều cao bình thường." },
      { value: "Grade 3", vi: "Độ 3", meaning: "Không đồng nhất, tín hiệu xám; ranh giới nhân và vòng xơ không rõ; chiều cao bình thường hoặc giảm nhẹ." },
      { value: "Grade 4", vi: "Độ 4", meaning: "Không đồng nhất, tín hiệu xám đến đen; mất ranh giới nhân và vòng xơ; chiều cao bình thường hoặc giảm vừa." },
      { value: "Grade 5", vi: "Độ 5", meaning: "Tín hiệu đen, mất ranh giới; khe đĩa xẹp." },
    ],
  },
  disc_narrowing: {
    short: "Hẹp khe đĩa",
    full: "Hẹp khe đĩa đệm",
    en: "Disc narrowing",
    source: "SpineNet",
    definition: "Chiều cao của đĩa đệm giảm đi.",
    levels: [
      { value: "Grade 1", vi: "Độ 1", meaning: "Không hẹp." },
      { value: "Grade 2", vi: "Độ 2", meaning: "Hẹp, mức tăng dần từ độ 2 tới độ 4." },
      { value: "Grade 3", vi: "Độ 3", meaning: "Hẹp, mức tăng dần từ độ 2 tới độ 4." },
      { value: "Grade 4", vi: "Độ 4", meaning: "Hẹp rất nặng." },
    ],
    caveat: "Bài báo SpineNetV2 chỉ định nghĩa hai đầu thang (1 = không hẹp, 4 = hẹp rất nặng); độ 2 và 3 là các mức trung gian.",
  },
  spondylolisthesis: {
    short: "Trượt đốt sống",
    full: "Trượt đốt sống",
    en: "Spondylolisthesis",
    source: "SpineNet",
    definition: "Đốt sống trượt ra trước so với đốt bên dưới, thường do khuyết eo (pars interarticularis).",
    levels: [
      { value: "None", vi: "Không", meaning: "Không trượt." },
      { value: "Grade I", vi: "Độ I", meaning: "Trượt mức độ I." },
      { value: "Grade II", vi: "Độ II trở lên", meaning: "Trượt từ độ II trở lên — lớp này gộp mọi mức từ II trở đi." },
    ],
    caveat: "Bài báo SpineNetV2 mô tả nhãn này là nhị phân, nhưng mạng thực tế có 3 đầu ra và nhãn huấn luyện gộp mọi mức ≥ II vào lớp cuối. Vì vậy lớp cuối là “độ II trở lên”, không phải đúng độ II.",
  },
  upper_endplate_defect: {
    short: "Tấm tận trên",
    full: "Tổn thương tấm tận phía trên",
    en: "Upper endplate defect",
    source: "SpineNet",
    definition: "Bất thường hoặc tổn thương tấm tận ở phía trên tầng đĩa đang xét.",
    levels: BINARY("Có bất thường hoặc tổn thương tấm tận."),
  },
  lower_endplate_defect: {
    short: "Tấm tận dưới",
    full: "Tổn thương tấm tận phía dưới",
    en: "Lower endplate defect",
    source: "SpineNet",
    definition: "Bất thường hoặc tổn thương tấm tận ở phía dưới tầng đĩa đang xét.",
    levels: BINARY("Có bất thường hoặc tổn thương tấm tận."),
  },
  upper_marrow: {
    short: "Tuỷ xương trên",
    full: "Thay đổi tuỷ xương phía trên (Modic)",
    en: "Upper marrow",
    source: "SpineNet",
    definition: "Thay đổi tín hiệu tuỷ xương của thân đốt sống ở phía trên tầng đĩa.",
    levels: BINARY("Có thay đổi tín hiệu tuỷ xương."),
    caveat: "Nhãn huấn luyện gộp Modic type 1, 2, 3 và hỗn hợp thành “Có”, nên nhãn này không phân biệt type.",
  },
  lower_marrow: {
    short: "Tuỷ xương dưới",
    full: "Thay đổi tuỷ xương phía dưới (Modic)",
    en: "Lower marrow",
    source: "SpineNet",
    definition: "Thay đổi tín hiệu tuỷ xương của thân đốt sống ở phía dưới tầng đĩa.",
    levels: BINARY("Có thay đổi tín hiệu tuỷ xương."),
    caveat: "Nhãn huấn luyện gộp Modic type 1, 2, 3 và hỗn hợp thành “Có”, nên nhãn này không phân biệt type.",
  },
  disc_herniation: {
    short: "Thoát vị đĩa",
    full: "Thoát vị đĩa đệm",
    en: "Disc herniation",
    source: "SpineNet",
    definition: "Nhân nhầy (nucleus pulposus) thoát ra qua vòng xơ (annulus fibrosus), có thể chèn ép thần kinh.",
    levels: BINARY("Có thoát vị."),
  },
};

/** Card order: the thesis model's three first, then SpineNet's eight. */
export const CONDITION_ORDER = [
  "canal_stenosis", "left_foraminal", "right_foraminal",
  "pfirrmann", "disc_narrowing", "disc_herniation", "spondylolisthesis",
  "upper_endplate_defect", "lower_endplate_defect", "upper_marrow", "lower_marrow",
];

/** Column header: Vietnamese when asked for and known, else the English. */
export function conditionHeader(key: string, lang: Lang, fallback: string): string {
  return lang === "vi" ? (CONDITIONS[key]?.short ?? fallback) : fallback;
}

/**
 * The label a stored severity is SHOWN as. The stored value is untouched.
 *
 * Looked up per condition, not globally: "Grade II" is "độ II trở lên" for
 * spondylolisthesis, and the same string could mean something else under a
 * condition that adds it later.
 */
export function severityLabel(condition: string, value: string, lang: Lang): string {
  if (lang !== "vi") return value;
  const level = CONDITIONS[condition]?.levels.find((l) => l.value === value);
  return level ? (level.short ?? level.vi) : value;
}

/** Guards the claim above: every value a head can emit has a Vietnamese label. */
export function untranslatedSeverities(): string[] {
  const missing: string[] = [];
  for (const [condition, values] of Object.entries(CONDITION_SEVERITIES)) {
    for (const v of values) {
      if (!CONDITIONS[condition]?.levels.some((l) => l.value === v)) {
        missing.push(`${condition}:${v}`);
      }
    }
  }
  return missing;
}

/** Segmented structure names, TotalSpineSeg style ("vertebrae_L1", "disc_L4_L5"). */
export function anatomyName(raw: string, english: string, lang: Lang): string {
  if (lang !== "vi") return english;
  if (raw.startsWith("vertebrae_")) return `Đốt sống ${raw.slice(10)}`;
  if (raw.startsWith("disc_")) return `Đĩa đệm ${raw.slice(5).replace(/_/g, "-")}`;
  const named: Record<string, string> = {
    spinal_cord: "Tuỷ sống",
    spinal_canal: "Ống sống",
    sacrum: "Xương cùng",
  };
  return named[raw] ?? english;
}
