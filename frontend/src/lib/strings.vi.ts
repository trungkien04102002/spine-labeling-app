/**
 * Vietnamese for the clinician-facing screens (worklist, viewer, grade
 * table, mask toolbar). Keys are the English source strings; see lib/i18n.
 *
 * Condition names and severity grades are left in English on purpose --
 * Vietnamese radiologists read and report those in English. Generated from
 * the t("...") calls in the source, so a key here that no longer appears
 * there is dead and a string there with no key here falls back to English.
 */
import { registerVi } from "./i18n";

registerVi({
  "Connecting":
    "Đang kết nối",
  "Online":
    "Trực tuyến",
  "Offline":
    "Mất kết nối",
  "Delete study \"{id}\"? This cannot be undone.":
    "Xoá ca \"{id}\"? Không thể hoàn tác.",
  "Spine Labeling":
    "Spine Labeling",
  "Lumbar MRI · AI-assisted grading":
    "MRI cột sống thắt lưng · Chấm điểm có AI hỗ trợ",
  "A 19-question survey, about 5 minutes":
    "Phiếu 19 câu, khoảng 5 phút",
  "Rate this software":
    "Đánh giá phần mềm",
  "The correction queue, the batches already sent, and what to run next":
    "Hàng đợi hiệu chỉnh, các lô đã gửi, và việc cần chạy tiếp",
  "Feedback":
    "Phản hồi",
  "{n} waiting":
    "{n} đang chờ",
  "Which checkpoint grades new studies, and how a new one is approved":
    "Mô hình nào đang chấm ca mới, và cách duyệt mô hình mới",
  "Model:":
    "Mô hình:",
  "{n} to review":
    "{n} chờ duyệt",
  "Worklist":
    "Danh sách ca",
  "Search patient, MRN, study…":
    "Tìm bệnh nhân, mã BN, mã ca…",
  "All":
    "Tất cả",
  "Cancel":
    "Huỷ",
  "+ New study":
    "+ Ca mới",
  "Study ID":
    "Mã ca",
  "e.g. case_042":
    "vd. case_042",
  "Patient name":
    "Tên bệnh nhân",
  "existing name groups; new one creates a patient":
    "trùng tên thì gộp; tên mới sẽ tạo bệnh nhân mới",
  "Modality":
    "Loại chụp",
  "Create":
    "Tạo",
  "{n} ready":
    "{n} sẵn sàng",
  "Rename patient":
    "Đổi tên bệnh nhân",
  "Ready":
    "Sẵn sàng",
  "No volume":
    "Chưa có ảnh",
  "DICOM series (.zip), or .mha / .nii / .nii.gz volume":
    "Chuỗi DICOM (.zip), hoặc tệp .mha / .nii / .nii.gz",
  "Uploading…":
    "Đang tải lên…",
  "Replace":
    "Thay ảnh",
  "Upload":
    "Tải lên",
  "Open →":
    "Mở →",
  "Open":
    "Mở",
  "Delete study":
    "Xoá ca",
  "No studies yet — create one to get started.":
    "Chưa có ca nào — tạo ca mới để bắt đầu.",
  "No matches for the current search / filter.":
    "Không có ca nào khớp với từ khoá / bộ lọc.",
  "{n} patient":
    "{n} bệnh nhân",
  "{n} patients":
    "{n} bệnh nhân",
  "{n} study":
    "{n} ca",
  "{n} studies":
    "{n} ca",
  "acquisition":
    "thông số chụp",
  "Series":
    "Chuỗi ảnh",
  "Loading…":
    "Đang tải…",
  "The grades come from the":
    "Điểm được chấm trên chuỗi",
  "series. Browse any series freely — switching does not change the grades.":
    "— có thể xem các chuỗi khác thoải mái, đổi chuỗi không làm đổi điểm.",
  "Browse any plane freely. “Run AI grading” always grades the sagittal series, whichever one you are viewing.":
    "Có thể xem mọi mặt cắt. “Chấm điểm bằng AI” luôn chấm trên chuỗi sagittal, bất kể đang xem chuỗi nào.",
  "Saved as a new corrected version.":
    "Đã lưu thành một phiên bản hiệu chỉnh mới.",
  "No corrections are waiting to be sent.":
    "Không có hiệu chỉnh nào đang chờ gửi.",
  "Sent {n} correction(s) as batch {id}. Re-training runs offline, and the new model version has to be reviewed before it grades anyone.":
    "Đã gửi {n} hiệu chỉnh thành lô {id}. Việc huấn luyện lại chạy riêng, và phiên bản mô hình mới phải được duyệt trước khi chấm cho bất kỳ ai.",
  "← Worklist":
    "← Danh sách ca",
  "Study {id}":
    "Ca {id}",
  "Grading…":
    "Đang chấm…",
  "✨ Run AI grading":
    "✨ Chấm điểm bằng AI",
  "Grading progress":
    "Tiến độ chấm",
  "Usually 2–4 minutes on the GPU server. You can leave this page — the run continues on the server and the result is saved.":
    "Thường mất 2–4 phút trên máy chủ GPU. Bác sĩ có thể rời trang — việc chấm vẫn chạy trên máy chủ và kết quả được lưu lại.",
  "Saving…":
    "Đang lưu…",
  "Undo mask edit":
    "Hoàn tác sửa mask",
  "Undo":
    "Hoàn tác",
  "Wheel: scroll slices · Left drag: window/level · Middle drag: pan · Right drag: zoom":
    "Cuộn chuột: chuyển lát cắt · Kéo chuột trái: chỉnh cửa sổ/mức · Kéo chuột giữa: di chuyển · Kéo chuột phải: phóng to",
  "About this tool":
    "Giới thiệu công cụ",
  "This tool automatically reads a lumbar spine MRI and produces radiological grades for each intervertebral disc level (T12–L1 down to L5–S1). Click a level in the table to jump to its slice; you can correct any grade and save it.":
    "Công cụ tự động đọc phim MRI cột sống thắt lưng và chấm điểm từng tầng đĩa đệm (từ T12–L1 đến L5–S1). Bấm vào một tầng trong bảng để nhảy tới lát cắt tương ứng; bác sĩ có thể sửa bất kỳ điểm nào rồi lưu lại.",
  "What it predicts":
    "Các nhãn công cụ dự đoán",
  "Central canal and left/right foraminal stenosis come from the project's fine-tuned CBAM model; the other 8 grades come from the upstream SpineNet pipeline.":
    "Hẹp ống sống trung tâm và hẹp lỗ liên hợp trái/phải do mô hình CBAM tinh chỉnh của đề tài chấm; 8 nhãn còn lại do SpineNet chấm.",
  "⚠ Research use only — this is not a diagnostic tool or a medical device.":
    "⚠ Chỉ dùng cho nghiên cứu — đây không phải công cụ chẩn đoán hay thiết bị y tế.",
  "Structures":
    "Cấu trúc giải phẫu",
  "Click it on the image, or pick it here — the fill tools are off until a structure is chosen.":
    "Bấm vào cấu trúc trên ảnh, hoặc chọn ở đây — công cụ tô bị khoá cho tới khi chọn một cấu trúc.",
  "Click a structure here, or point at it on the image, to switch what is painted.":
    "Bấm vào một cấu trúc ở đây, hoặc chỉ vào nó trên ảnh, để đổi cấu trúc đang tô.",
  "Doctor feedback":
    "Phản hồi của bác sĩ",
  "When you fix a grade in the table above and press “Save corrections”, the change is recorded as expert feedback. Send them to the model when you are ready — nothing is used for training until you do.":
    "Khi bác sĩ sửa một điểm trong bảng phía trên và bấm “Lưu hiệu chỉnh”, thay đổi được ghi nhận là phản hồi chuyên gia. Gửi cho mô hình khi đã sẵn sàng — không có gì được dùng để huấn luyện cho tới lúc đó.",
  "Waiting to be sent":
    "Đang chờ gửi",
  "Already sent":
    "Đã gửi",
  "{n} batch(es)":
    "{n} lô",
  "Sending…":
    "Đang gửi…",
  "Send {n} correction(s) to the model":
    "Gửi {n} hiệu chỉnh cho mô hình",
  "Sending only queues the corrections. Re-training runs offline, and a new model version has to be reviewed and switched on before it grades anyone — so this never changes the next patient's result.":
    "Gửi chỉ đưa hiệu chỉnh vào hàng đợi. Việc huấn luyện lại chạy riêng, và phiên bản mô hình mới phải được duyệt và bật lên mới chấm cho bệnh nhân — nên việc gửi không bao giờ làm đổi kết quả của bệnh nhân kế tiếp.",
  "Model versions — review and switch on →":
    "Phiên bản mô hình — duyệt và bật →",
  "Abnormality grades":
    "Điểm bất thường",
  "Canal and foraminal stenosis are missing.":
    "Thiếu nhãn hẹp ống sống và hẹp lỗ liên hợp.",
  "Those three come from the fine-tuned CBAM model, which grades crops cut from the lumbar disc labels in the segmentation. The mask for this study has no lumbar discs, so there was nothing to grade — only the 8 upstream SpineNet labels are shown. Re-upload the study and run again; if it persists, the segmentation is wrong, not the grading.":
    "Ba nhãn này do mô hình CBAM chấm, trên các vùng cắt từ nhãn đĩa đệm thắt lưng trong phân vùng. Phân vùng của ca này không có đĩa đệm thắt lưng nên không có gì để chấm — chỉ hiện 8 nhãn của SpineNet. Hãy tải ảnh lên lại và chấm lại; nếu vẫn vậy thì lỗi nằm ở phân vùng, không phải ở phần chấm điểm.",
  "No segmentation for this study, so there is nothing these grades were measured from. Click “✨ Run AI grading” to segment and grade the current image.":
    "Ca này chưa có phân vùng, nên các điểm này không có căn cứ trên ảnh hiện tại. Bấm “✨ Chấm điểm bằng AI” để phân vùng và chấm lại ảnh này.",
  "Undo mask edit (Ctrl+Z)":
    "Hoàn tác sửa mask (Ctrl+Z)",
  "Undo (Ctrl+Z)":
    "Hoàn tác (Ctrl+Z)",
  "Redo mask edit (Ctrl+Shift+Z)":
    "Làm lại sửa mask (Ctrl+Shift+Z)",
  "Redo (Ctrl+Shift+Z)":
    "Làm lại (Ctrl+Shift+Z)",
  "Redo mask edit":
    "Làm lại sửa mask",
  "Redo":
    "Làm lại",
  "Export":
    "Xuất dữ liệu",
  "unsaved":
    "chưa lưu",
  "Model: {v}. Click a level to jump; change a severity, then Save.":
    "Mô hình: {v}. Bấm vào một tầng để nhảy tới lát cắt; sửa mức độ rồi bấm Lưu.",
  "SpineNet-labelled mid-sagittal slice":
    "Lát cắt sagittal giữa có nhãn của SpineNet",
  "No AI results yet — click “✨ Run AI grading” (top right).":
    "Chưa có kết quả AI — bấm “✨ Chấm điểm bằng AI” (góc trên bên phải).",
  "Level":
    "Tầng",
  "Graded by the vendored upstream SpineNet. Corrections here are saved and exported, but re-training does not use them.":
    "Do SpineNet chấm. Hiệu chỉnh ở cột này được lưu và xuất ra, nhưng không dùng để huấn luyện lại.",
  "Jump to this disc":
    "Nhảy tới đĩa đệm này",
  "confidence {p}%":
    "độ tin cậy {p}%",
  "Graded by the vendored upstream SpineNet. Corrections to these columns are saved with the study and included in the export, but the re-training loop does not use them — it re-trains only Canal, L. foraminal and R. foraminal, the three heads of the app's own model.":
    "Do SpineNet chấm. Hiệu chỉnh ở các cột này được lưu cùng ca và có trong tệp xuất, nhưng vòng huấn luyện lại không dùng chúng — nó chỉ huấn luyện lại Canal, L. foraminal và R. foraminal, ba nhánh của mô hình riêng của đề tài.",
  "Segmentation":
    "Phân vùng",
  "Opacity":
    "Độ trong",
  "Edit mask":
    "Sửa mask",
  "Point & select":
    "Chỉ & chọn",
  "Undo the last edit (Ctrl+Z)":
    "Hoàn tác thao tác vừa rồi (Ctrl+Z)",
  "Save":
    "Lưu",
  "Brush":
    "Cọ",
  "Circle":
    "Hình tròn",
  "Rectangle":
    "Hình chữ nhật",
  "Fill":
    "Tô",
  "Erase":
    "Xoá",
  "Size":
    "Cỡ",
  "Click the structure on the image — nothing is selected yet.":
    "Bấm vào cấu trúc trên ảnh — chưa chọn gì.",
  "Click the structure on the image.":
    "Bấm vào cấu trúc trên ảnh.",
  "Nothing there — that is background.":
    "Không có gì ở đó — đó là nền.",
  "Sagittal":
    "Sagittal",
  "Axial":
    "Axial",
  "Coronal":
    "Coronal",
  "Save changes":
    "Lưu thay đổi",
  "Save mask":
    "Lưu mask",
  "Save corrections":
    "Lưu hiệu chỉnh",
  "Starting":
    "Đang khởi động",
  "Segmenting vertebrae (TotalSpineSeg)":
    "Đang phân vùng đốt sống (TotalSpineSeg)",
  "Detecting and grading discs (SpineNet)":
    "Đang phát hiện và chấm đĩa đệm (SpineNet)",
  "Merging results":
    "Đang gộp kết quả",
  "Finished":
    "Hoàn tất",
  "Disc degeneration, from healthy (1) to severely degenerated (5).":
    "Thoái hoá đĩa đệm, từ bình thường (1) tới thoái hoá nặng (5).",
  "Loss of intervertebral disc height.":
    "Giảm chiều cao đĩa đệm.",
  "Narrowing of the central spinal canal.":
    "Hẹp ống sống trung tâm.",
  "Narrowing of the left/right nerve-exit foramen.":
    "Hẹp lỗ liên hợp trái/phải, nơi rễ thần kinh đi ra.",
  "Forward slippage of one vertebra over another.":
    "Trượt đốt sống ra trước so với đốt bên dưới.",
  "Damage to the vertebral endplate.":
    "Tổn thương tấm tận đốt sống.",
  "Modic vertebral bone-marrow signal changes.":
    "Thay đổi tín hiệu tuỷ xương đốt sống kiểu Modic.",
  "Protrusion/extrusion of disc material.":
    "Lồi/thoát vị nhân đệm.",
});
