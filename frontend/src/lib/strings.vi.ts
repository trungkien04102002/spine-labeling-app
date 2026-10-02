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
  "A short survey, about 5 minutes":
    "Phiếu đánh giá, khoảng 5 phút",
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
    "Có thể xem mọi mặt cắt. “Chạy chẩn đoán AI” luôn chấm trên chuỗi sagittal, bất kể đang xem chuỗi nào.",
  "Saved as a new corrected version.":
    "Đã lưu các điểm bác sĩ vừa sửa.",
  "No corrections are waiting to be sent.":
    "Không có hiệu chỉnh nào đang chờ gửi.",
  "Sent {n} correction(s). Thank you — they are reviewed later and do not change any result right away.":
    "Đã gửi {n} hiệu chỉnh. Cảm ơn bác sĩ — hiệu chỉnh sẽ được xem xét sau, không làm đổi kết quả nào ngay lập tức.",
  "← Worklist":
    "← Danh sách ca",
  "Study {id}":
    "Ca {id}",
  "Grading…":
    "Đang chấm…",
  "✨ Run AI grading":
    "✨ Chạy chẩn đoán AI",
  "Grading progress":
    "Tiến độ chấm",
  "Usually 2–4 minutes on the GPU server. You can leave this page — the run continues on the server and the result is saved.":
    "Thường mất 2–4 phút trên máy chủ GPU. Bác sĩ có thể rời trang — việc chấm vẫn chạy trên máy chủ và kết quả được lưu lại.",
  "Saving…":
    "Đang lưu…",
  "Undo mask edit":
    "Hoàn tác sửa vùng tô",
  "Undo":
    "Hoàn tác",
  "Wheel: scroll slices · Left drag: window/level · Middle drag: pan · Right drag: zoom":
    "Cuộn chuột: chuyển lát cắt · Kéo chuột trái: chỉnh cửa sổ/mức · Kéo chuột giữa: di chuyển · Kéo chuột phải: phóng to",
  "About this tool":
    "Giới thiệu công cụ",
  "This tool automatically reads a lumbar spine MRI and produces radiological grades for each intervertebral disc level (T12–L1 down to L5–S1). Click a level in the table to jump to its slice; you can correct any grade and save it.":
    "Công cụ tự động đọc phim MRI cột sống thắt lưng và chấm điểm từng tầng đĩa đệm (từ T12–L1 đến L5–S1). Bấm vào một tầng trong bảng để nhảy tới lát cắt tương ứng; bác sĩ có thể sửa bất kỳ điểm nào rồi lưu lại.",
  "What it predicts":
    "AI chấm những gì",
  "⚠ Research use only — this is not a diagnostic tool or a medical device.":
    "⚠ Chỉ dùng cho nghiên cứu — đây không phải công cụ chẩn đoán hay thiết bị y tế.",
  "Structures":
    "Cấu trúc giải phẫu",
  "Click it on the image, or pick it here — the fill tools are off until a structure is chosen.":
    "Bấm lên ảnh hoặc chọn tên ở đây để chọn đốt sống / đĩa đệm cần tô — chưa chọn thì chưa tô được.",
  "Click a structure here, or point at it on the image, to switch what is painted.":
    "Bấm vào tên ở đây hoặc bấm lên ảnh để chọn đốt sống / đĩa đệm cần tô.",
  "Doctor feedback":
    "Phản hồi của bác sĩ",
  "When you fix a grade in the table above and press “Save corrections”, the change is recorded as expert feedback. Send them when you are ready.":
    "Khi bác sĩ sửa một điểm trong bảng phía trên và bấm “Lưu hiệu chỉnh”, thay đổi được ghi nhận là phản hồi chuyên gia. Bấm gửi khi đã sẵn sàng.",
  "Waiting to be sent":
    "Đang chờ gửi",
  "Already sent":
    "Đã gửi",
  "{n} batch(es)":
    "{n} lô",
  "Sending…":
    "Đang gửi…",
  "Send {n} correction(s)":
    "Gửi {n} hiệu chỉnh",
  "Sent corrections are reviewed later; they do not change the next patient's result.":
    "Hiệu chỉnh đã gửi sẽ được xem xét sau, không làm đổi kết quả của bệnh nhân kế tiếp.",
  "Model versions — review and switch on →":
    "Phiên bản mô hình — duyệt và bật →",
  "Abnormality grades":
    "Điểm bất thường",
  "Canal and foraminal stenosis are missing.":
    "Thiếu nhãn hẹp ống sống và hẹp lỗ liên hợp.",
  "They are graded around the lumbar discs found by the segmentation, and the segmentation of this study has no lumbar discs — only the other 8 labels are shown. Re-upload the study and run again; if it persists, check the segmentation.":
    "Ba nhãn này được chấm quanh các đĩa đệm thắt lưng mà AI tô trên phim, nhưng ở ca này AI không tô được đĩa đệm thắt lưng nào — chỉ hiện 8 nhãn còn lại. Hãy tải ảnh lên lại và chạy lại; nếu vẫn vậy, hãy xem lại vùng tô.",
  "No segmentation for this study, so there is nothing these grades were measured from. Click “✨ Run AI grading” to segment and grade the current image.":
    "Ca này chưa có vùng tô, nên các điểm này không khớp với ảnh đang xem. Bấm “✨ Chạy chẩn đoán AI” để AI tô và chấm lại ảnh này.",
  "Undo mask edit (Ctrl+Z)":
    "Hoàn tác sửa vùng tô (Ctrl+Z)",
  "Undo (Ctrl+Z)":
    "Hoàn tác (Ctrl+Z)",
  "Redo mask edit (Ctrl+Shift+Z)":
    "Làm lại sửa vùng tô (Ctrl+Shift+Z)",
  "Redo (Ctrl+Shift+Z)":
    "Làm lại (Ctrl+Shift+Z)",
  "Redo mask edit":
    "Làm lại sửa vùng tô",
  "Redo":
    "Làm lại",
  "Export":
    "Xuất dữ liệu",
  "unsaved":
    "chưa lưu",
  "Click a level to jump; change a severity, then Save.":
    "Bấm vào một tầng để nhảy tới lát cắt; sửa mức độ rồi bấm Lưu.",
  "SpineNet-labelled mid-sagittal slice":
    "Lát cắt sagittal giữa có nhãn của SpineNet",
  "No AI results yet — click “✨ Run AI grading” (top right).":
    "Chưa có kết quả AI — bấm “✨ Chạy chẩn đoán AI” (góc trên bên phải).",
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
    "Vùng tô",
  "Opacity":
    "Độ trong",
  "Edit mask":
    "Sửa vùng tô",
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
    "Lưu vùng tô",
  "Save corrections":
    "Lưu hiệu chỉnh",
  "Starting":
    "Đang khởi động",
  "Segmenting vertebrae":
    "Đang tô đốt sống và đĩa đệm",
  "Detecting and grading discs":
    "Đang phát hiện và chấm đĩa đệm",
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
  "not on this scale":
    "sai thang",
  "Low confidence ({p}%) — review":
    "Độ tin cậy thấp ({p}%) — nên kiểm lại",
  "Choose a structure…":
    "Chọn cấu trúc…",
  "Label reference: what each grade means":
    "Bảng tra nhãn: mỗi mức điểm nghĩa là gì",
  "More columns to the side — use the arrows, drag the bar, or Shift + scroll.":
    "Còn cột ở bên cạnh — bấm mũi tên, kéo thanh cuộn, hoặc giữ Shift rồi cuộn chuột.",
  "Scroll left":
    "Cuộn sang trái",
  "Scroll right":
    "Cuộn sang phải",
  "Room":
    "Phòng",
  "Switch":
    "Đổi",
  "Hide samples":
    "Ẩn ca mẫu",
  "+ Sample case":
    "+ Ca mẫu",
  "Sample cases to try":
    "Ca mẫu để thử",
  "Already graded by the AI. Your copy is yours alone — edit it freely.":
    "Đã được AI chấm sẵn. Bản sao là của riêng bác sĩ — cứ sửa thoải mái.",
  "Adding…":
    "Đang thêm…",
  "Your room is empty. Add a sample case above, or create a study and upload your own scan.":
    "Phòng của bác sĩ chưa có ca nào. Thêm một ca mẫu ở trên, hoặc tạo ca mới và tải phim của bác sĩ lên.",
  "Your name":
    "Tên của bác sĩ",
  "e.g. Dr. Minh":
    "vd. BS Minh",
  "Entering…":
    "Đang vào…",
  "Enter my room":
    "Vào phòng",
  "Each person gets a private room: your studies, your corrections and your answers are seen by no other participant.":
    "Mỗi bác sĩ một phòng riêng: ca bệnh, các điểm đã sửa và phiếu đánh giá của bác sĩ, người khác không xem được.",
  "Type the same name again, on any computer, to come back to your room.":
    "Nhập lại đúng tên này, trên bất kỳ máy nào, để quay lại phòng của mình.",
  "Pick a name others will not use — two people with the same name share one room.":
    "Chọn tên không trùng người khác — hai người cùng tên sẽ vào chung một phòng.",
  "Wrong passphrase.":
    "Sai mật khẩu.",
  "Admin":
    "Quản trị",
  "For whoever runs the trial.":
    "Dành cho người điều hành thử nghiệm.",
  "Passphrase":
    "Mật khẩu",
  "← Back to the clinician view":
    "← Về giao diện bác sĩ",
  "Clinician rooms":
    "Phòng bác sĩ",
  "Nobody has entered a room yet.":
    "Chưa có ai vào phòng.",
  "Name":
    "Tên",
  "Joined":
    "Vào lúc",
  "Studies":
    "Ca",
  "Corrections":
    "Hiệu chỉnh",
  "Surveys":
    "Phiếu",
  "Delete {who}'s response for good? Use this only for test submissions.":
    "Xoá vĩnh viễn phiếu của {who}? Chỉ dùng cho phiếu thử nghiệm.",
  "No responses yet.":
    "Chưa có phiếu nào.",
  "(no room)":
    "(không có phòng)",
  "Delete":
    "Xoá",
  "Survey results":
    "Kết quả khảo sát",
  "Each response":
    "Từng phiếu",
  "Export trial data":
    "Xuất dữ liệu",
  "Everything the trial produced, in one file, straight to this computer. Download it before destroying the rented box — its disk goes with it.":
    "Toàn bộ dữ liệu thử nghiệm trong một tệp, tải thẳng về máy này. Tải trước khi huỷ máy thuê — ổ đĩa của nó mất theo.",
  "Preparing…":
    "Đang chuẩn bị…",
  "⬇ Download everything (.zip)":
    "⬇ Tải toàn bộ (.zip)",
  "One row per room: name, when they joined, how much they did.":
    "Mỗi dòng một phòng: tên, lúc vào, đã làm bao nhiêu.",
  "One row per questionnaire; opens in Excel with Vietnamese intact.":
    "Mỗi dòng một phiếu; mở bằng Excel không lỗi tiếng Việt.",
  "The text of every Q column, so the answers stay readable.":
    "Nội dung từng cột Q, để đọc được câu trả lời.",
  "Every grade a clinician changed, with their room.":
    "Mọi điểm bác sĩ đã sửa, kèm phòng.",
  "A copy of the whole database, for anything the CSVs miss.":
    "Bản sao toàn bộ cơ sở dữ liệu, cho những gì CSV không có.",
  "Images clinicians uploaded are not in the zip — they can be hundreds of MB. Copy them off the box separately; see DEPLOY_VAST.md.":
    "Ảnh bác sĩ tải lên không nằm trong tệp zip — có thể tới hàng trăm MB. Chép riêng khỏi máy thuê; xem DEPLOY_VAST.md.",
  "Clinician view ↗":
    "Giao diện bác sĩ ↗",
  "Lock":
    "Khoá",
  "Feedback & re-training":
    "Phản hồi & huấn luyện lại",
  "Model versions":
    "Phiên bản mô hình",
  "clinical questions · {n} answers":
    "câu lâm sàng · {n} câu trả lời",
  "ease of use":
    "mức dễ dùng",
  "{n} response(s)":
    "{n} phiếu",
  "This link does not match any room. Ask for your link again, or enter your name.":
    "Link này không khớp phòng nào. Xin lại link, hoặc nhập tên của bác sĩ.",
  "Type the same name next time to come back to your room.":
    "Lần sau nhập đúng tên này để quay lại phòng của mình.",
  "✓ Copied":
    "✓ Đã chép",
  "Select and copy":
    "Bôi đen rồi chép",
  "Copy":
    "Sao chép",
  "Clinician's name":
    "Tên bác sĩ",
  "+ Create room and link":
    "+ Tạo phòng và link",
  "Send each clinician their link. If they lose it, copy it again from here.":
    "Gửi mỗi bác sĩ link của họ. Nếu họ làm mất, chép lại từ đây.",
  "Personal link":
    "Link riêng",
  "← Home":
    "← Trang chủ",
  "Label":
    "Nhãn",
  "Thesis model (CBAM)":
    "Mô hình đề tài (CBAM)",
  // Room PINs (2026-10-01)
  "Wrong PIN. Forgot it? Ask the organiser to send you your personal link again.":
    "Sai mã PIN. Nếu quên PIN, bác sĩ nhờ người quản lý gửi lại đường link riêng của mình.",
  "Hello, {name}":
    "Chào {name}",
  "Your room has no PIN yet. Choose one so that next time you can come back by picking your name and typing it.":
    "Phòng của bác sĩ chưa có mã PIN. Bác sĩ đặt một mã 4 số, lần sau chỉ cần bấm vào tên mình và nhập mã này là vào được.",
  "Entering the room of":
    "Vào phòng của",
  "Your 4-digit PIN":
    "Mã PIN 4 số của bác sĩ",
  "This room has no PIN yet — you will choose one after entering.":
    "Phòng này chưa có mã PIN — bác sĩ sẽ đặt mã ngay sau khi vào.",
  "Not you? Pick another name":
    "Không phải bác sĩ? Chọn tên khác",
  "Pick your name":
    "Bác sĩ bấm vào tên của mình",
  "First time here, and your name is not in the list?":
    "Lần đầu sử dụng, chưa có tên trong danh sách?",
  "Create my room":
    "Tạo phòng mới",
  "This link does not match any room. Ask for your link again, or pick your name.":
    "Đường link này không đúng phòng nào. Bác sĩ xin lại link, hoặc bấm vào tên của mình ở trên.",
  "Only once. Next time, pick your name from the list and type your PIN.":
    "Chỉ làm một lần. Lần sau bác sĩ bấm vào tên mình trong danh sách và nhập mã PIN.",
  "“{name}” already has a room.":
    "Tên “{name}” đã có phòng rồi.",
  "Enter that room":
    "Vào phòng đó",
  "Back to the list of names":
    "Quay lại danh sách tên",
  "Choose a 4-digit PIN":
    "Đặt mã PIN 4 số",
  "Type the PIN again":
    "Nhập lại mã PIN",
  "The two PINs do not match.":
    "Hai lần nhập không giống nhau.",
  "Save PIN":
    "Lưu mã PIN",
  "Your room has no PIN yet":
    "Phòng của bác sĩ chưa có mã PIN",
  "Choose a 4-digit PIN. Next time, pick your name on the first screen and type it to come back here.":
    "Bác sĩ đặt mã 4 số. Lần sau, ở trang đầu tiên bấm vào tên mình và nhập mã này là quay lại đây.",
  "That name already has a room — its link is in the list below.":
    "Tên này đã có phòng — link của phòng nằm trong danh sách bên dưới.",
  "Reset the PIN of “{name}”? Their room opens without a PIN until they choose a new one.":
    "Đặt lại PIN của “{name}”? Phòng sẽ mở không cần PIN cho tới khi bác sĩ đặt mã mới.",
  "Send each clinician their link. If they lose it or forget their PIN, copy it again from here — the link opens the room without a PIN.":
    "Gửi mỗi bác sĩ link của họ. Nếu bác sĩ mất link hoặc quên PIN, sao chép lại từ đây — mở bằng link thì không cần PIN.",
  "PIN":
    "PIN",
  "Set":
    "Đã đặt",
  "Reset PIN":
    "Đặt lại PIN",
  "Not set yet":
    "Chưa đặt",
  "The PIN must be exactly 4 digits.":
    "Mã PIN phải gồm đúng 4 chữ số.",
  "This room already has a PIN.":
    "Phòng này đã có mã PIN.",
  // Comparison model B (components/Viewer/ReferenceBPanel.tsx)
  "For comparison: model B":
    "Kết quả tham khảo: mô hình B",
  "Another AI model, run alongside for you to compare. It reads only one image (the middle slice, shown here) and answers for the whole image, not per disc level. It does not change the grades above.":
    "Một mô hình AI khác, chạy song song để bác sĩ so sánh. Mô hình này chỉ đọc một ảnh (lát giữa, hình bên trái) và trả lời chung cho cả ảnh, không chia theo từng tầng đĩa đệm. Kết quả này không làm thay đổi bảng phía trên.",
  "Running model B…":
    "Đang chạy mô hình B…",
  "Image model B read":
    "Ảnh mô hình B đã đọc",
  "Slice {i} of {n}":
    "Lát {i} / {n}",
  "Finding":
    "Dấu hiệu",
  "Probability":
    "Xác suất",
  "Result":
    "Kết quả",
  "Yes":
    "Có",
  "No":
    "Không",
  "“No finding” scored highest, so model B counts every other finding as No.":
    "“Không thấy bất thường” có xác suất cao nhất, nên mô hình B tính mọi dấu hiệu còn lại là Không.",
  "UP endplate":
    "Tổn thương tấm tận trên",
  "LOW endplate":
    "Tổn thương tấm tận dưới",
  "Spondylolisthesis":
    "Trượt đốt sống",
  "Disc herniation":
    "Thoát vị đĩa đệm",
  "Disc narrowing":
    "Hẹp khe đĩa đệm",
  "Disc bulging":
    "Phồng đĩa đệm",
  "Modic":
    "Thay đổi tuỷ xương (Modic)",
  "No Finding":
    "Không thấy bất thường",
  "Comparison model B":
    "Mô hình B (so sánh)",
  "Hide from clinicians":
    "Ẩn với bác sĩ",
  "Show to clinicians":
    "Hiện cho bác sĩ",
  "Model B runs after every AI grading and its answer is saved (in the export as reference_b.csv). This switch only decides whether clinicians see it, as a panel under the grade table.":
    "Mô hình B luôn chạy ngầm sau mỗi lần AI chấm và kết quả được lưu lại (trong file xuất dữ liệu là reference_b.csv). Nút này chỉ quyết định bác sĩ có thấy ô kết quả mô hình B dưới bảng phân độ hay không.",
  "Model B is not installed on this server.":
    "Máy chủ này chưa cài mô hình B.",
  "Now: shown to clinicians.":
    "Hiện tại: bác sĩ ĐANG thấy.",
  "Now: hidden from clinicians.":
    "Hiện tại: đang ẩn với bác sĩ.",
  "Model B's answer for every study it read, for comparison.":
    "Kết quả của mô hình B cho mọi ca nó đã đọc, để so sánh.",
});
