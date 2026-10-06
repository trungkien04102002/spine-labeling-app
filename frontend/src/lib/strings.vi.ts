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
    "Chưa có ca nào. Bấm “+ Ca mới” để bắt đầu.",
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
    "(có thể xem các chuỗi khác thoải mái, đổi chuỗi không làm đổi điểm).",
  "Browse any plane freely. “Run AI grading” always grades the sagittal series, whichever one you are viewing.":
    "Có thể xem mọi mặt cắt. “Chạy chẩn đoán AI” luôn chấm trên chuỗi sagittal, bất kể đang xem chuỗi nào.",
  "Saved as a new corrected version.":
    "Đã lưu các điểm bác sĩ vừa sửa.",
  "No corrections are waiting to be sent.":
    "Không có hiệu chỉnh nào đang chờ gửi.",
  "Sent {n} correction(s). Thank you — they are reviewed later and do not change any result right away.":
    "Đã gửi {n} hiệu chỉnh. Cảm ơn bác sĩ! Hiệu chỉnh sẽ được xem xét sau, không làm đổi kết quả nào ngay lập tức.",
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
  "Usually 1–2 minutes. Press it and leave it: you can even leave this page — the run continues on the server and the result is saved.":
    "Thường mất 1–2 phút. Cứ bấm rồi để đó chờ. Bác sĩ có thể rời trang, máy chủ vẫn chạy và tự lưu kết quả.",
  "Saving…":
    "Đang lưu…",
  "Undo mask edit":
    "Hoàn tác sửa vùng tô",
  "Undo":
    "Hoàn tác",
  "Mouse on the picture:":
    "Dùng chuột trên ảnh:",
  "Scroll the wheel: previous / next slice":
    "Lăn con lăn: chuyển sang lát cắt trước / sau",
  "Hold the left button and drag: brightness and contrast":
    "Giữ chuột trái rồi kéo: chỉnh độ sáng và độ tương phản",
  "Hold the right button and drag: zoom in / out":
    "Giữ chuột phải rồi kéo: phóng to / thu nhỏ",
  "Hold the wheel down and drag: move the picture":
    "Nhấn giữ con lăn rồi kéo: di chuyển ảnh",
  "No mouse (touchpad)? Use the ◀ ▶, ＋ －, brightness and contrast buttons just under the picture.":
    "Không có chuột (dùng touchpad)? Bấm các nút ◀ ▶, ＋ －, Độ sáng, Độ tương phản ngay dưới ảnh.",
  "About this tool":
    "Giới thiệu công cụ",
  "This tool automatically reads a lumbar spine MRI and produces radiological grades for each intervertebral disc level (T12–L1 down to L5–S1). Click a level in the table to jump to its slice; you can correct any grade and save it.":
    "Công cụ tự động đọc phim MRI cột sống thắt lưng và chấm điểm từng tầng đĩa đệm (từ T12–L1 đến L5–S1). Bấm vào một tầng trong bảng để nhảy tới lát cắt tương ứng; bác sĩ có thể sửa bất kỳ điểm nào rồi lưu lại.",
  "What it predicts":
    "AI chấm những gì",
  "⚠ Research use only — this is not a diagnostic tool or a medical device.":
    "⚠ Chỉ dùng cho nghiên cứu. Đây không phải công cụ chẩn đoán hay thiết bị y tế.",
  "Structures":
    "Cấu trúc giải phẫu",
  "Click it on the image, or pick it here — the fill tools are off until a structure is chosen.":
    "Bấm lên ảnh hoặc chọn tên ở đây để chọn đốt sống / đĩa đệm cần tô. Chưa chọn thì chưa tô được.",
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
    "Phiên bản mô hình: duyệt và bật →",
  "Abnormality grades":
    "Điểm bất thường",
  "Canal and foraminal stenosis are missing.":
    "Thiếu nhãn hẹp ống sống và hẹp lỗ liên hợp.",
  "They are graded around the lumbar discs found by the segmentation, and the segmentation of this study has no lumbar discs — only the other 8 labels are shown. Re-upload the study and run again; if it persists, check the segmentation.":
    "Ba nhãn này được chấm quanh các đĩa đệm thắt lưng mà AI tô trên phim, nhưng ở ca này AI không tô được đĩa đệm thắt lưng nào, nên chỉ hiện 8 nhãn còn lại. Hãy tải ảnh lên lại và chạy lại; nếu vẫn vậy, hãy xem lại vùng tô.",
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
    "Chưa có kết quả AI. Bấm “✨ Chạy chẩn đoán AI” (góc trên bên phải).",
  "Level":
    "Tầng",
  "Graded by the vendored upstream SpineNet. Corrections here are saved and exported, but re-training does not use them.":
    "Do SpineNet chấm. Hiệu chỉnh ở cột này được lưu và xuất ra, nhưng không dùng để huấn luyện lại.",
  "Jump to this disc":
    "Nhảy tới đĩa đệm này",
  "confidence {p}%":
    "độ tin cậy {p}%",
  "Graded by the vendored upstream SpineNet. Corrections to these columns are saved with the study and included in the export, but the re-training loop does not use them — it re-trains only Canal, L. foraminal and R. foraminal, the three heads of the app's own model.":
    "Do SpineNet chấm. Hiệu chỉnh ở các cột này được lưu cùng ca và có trong tệp xuất, nhưng vòng huấn luyện lại không dùng chúng. Vòng này chỉ huấn luyện lại Canal, L. foraminal và R. foraminal, ba nhánh của mô hình riêng của đề tài.",
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
    "Bấm vào cấu trúc trên ảnh (chưa chọn gì).",
  "Click the structure on the image.":
    "Bấm vào cấu trúc trên ảnh.",
  "Nothing there — that is background.":
    "Chỗ đó là nền, không có cấu trúc nào.",
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
  "This study is being graded right now. Wait until it finishes (about 1–2 minutes), then upload again.":
    "Ca này đang được AI chấm. Đợi chấm xong (khoảng 1–2 phút) rồi hãy tải ảnh lên lại.",
  "This study is being graded right now. Wait until it finishes, then delete it.":
    "Ca này đang được AI chấm. Đợi chấm xong rồi hãy xoá.",
  "Segmentation ready. Grading each disc":
    "Đã tô xong vùng giải phẫu (đang hiện trên ảnh). Đang chấm điểm từng đĩa đệm",
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
    "Tổn thương mâm sụn (tấm tận) đốt sống.",
  "Modic vertebral bone-marrow signal changes.":
    "Thay đổi tín hiệu tuỷ xương thân đốt sát mâm sụn (thay đổi Modic).",
  "Protrusion/extrusion of disc material.":
    "Lồi/thoát vị nhân đệm.",
  "not on this scale":
    "sai thang",
  "Low confidence ({p}%) — review":
    "Độ tin cậy thấp ({p}%), nên kiểm lại",
  "Choose a structure…":
    "Chọn cấu trúc…",
  "Label reference: what each grade means":
    "Bảng tra nhãn: mỗi mức điểm nghĩa là gì",
  "More columns to the side — use the arrows, drag the bar, or Shift + scroll.":
    "Còn cột ở bên cạnh: bấm mũi tên, kéo thanh cuộn, hoặc giữ Shift rồi cuộn chuột.",
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
    "Đã được AI chấm sẵn. Bản sao là của riêng bác sĩ, cứ sửa thoải mái.",
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
    "Chọn tên không trùng người khác, vì hai người cùng tên sẽ vào chung một phòng.",
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
    "Toàn bộ dữ liệu thử nghiệm trong một tệp, tải thẳng về máy này. Nhớ tải trước khi huỷ máy thuê, vì ổ đĩa của máy đó mất theo.",
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
    "Ảnh bác sĩ tải lên không nằm trong tệp zip (có thể tới hàng trăm MB). Chép riêng khỏi máy thuê, xem DEPLOY_VAST.md.",
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
    "Phòng này chưa có mã PIN. Bác sĩ sẽ đặt mã ngay sau khi vào.",
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
    "Tên này đã có phòng. Link của phòng nằm trong danh sách bên dưới.",
  "Reset the PIN of “{name}”? Their room opens without a PIN until they choose a new one.":
    "Đặt lại PIN của “{name}”? Phòng sẽ mở không cần PIN cho tới khi bác sĩ đặt mã mới.",
  "Send each clinician their link. If they lose it or forget their PIN, copy it again from here — the link opens the room without a PIN.":
    "Gửi mỗi bác sĩ link của họ. Nếu bác sĩ mất link hoặc quên PIN, sao chép lại từ đây. Mở bằng link thì không cần PIN.",
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
    "Kết quả tham khảo: mô hình AI B",
  "Another AI model, run alongside for you to compare. It reads only one image (the middle slice, shown here) and answers for the whole image, not per disc level. It does not change the grades above.":
    "Một mô hình AI khác, chạy song song để bác sĩ so sánh. Mô hình này chỉ đọc một ảnh (lát giữa, hình bên trái) và trả lời chung cho cả ảnh, không chia theo từng tầng đĩa đệm. Kết quả này không làm thay đổi bảng phía trên.",
  "Running model B…":
    "Đang chạy mô hình AI B…",
  "Image model B read":
    "Ảnh mô hình AI B đã đọc",
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
    "“Không thấy bất thường” có xác suất cao nhất, nên mô hình AI B tính mọi dấu hiệu còn lại là Không.",
  "UP endplate":
    "Tổn thương mâm sụn trên",
  "LOW endplate":
    "Tổn thương mâm sụn dưới",
  "Spondylolisthesis":
    "Trượt đốt sống",
  "Disc herniation":
    "Thoát vị đĩa đệm",
  "Disc narrowing":
    "Hẹp khe đĩa đệm",
  "Disc bulging":
    "Phồng đĩa đệm",
  "Modic":
    "Thay đổi Modic",
  "No Finding":
    "Không thấy bất thường",
  "Comparison model B":
    "Mô hình AI B (so sánh)",
  "Hide from clinicians":
    "Ẩn với bác sĩ",
  "Show to clinicians":
    "Hiện cho bác sĩ",
  "Model B runs after every AI grading and its answer is saved (in the export as reference_b.csv). This switch only decides whether clinicians see it, as a panel under the grade table.":
    "Mô hình AI B luôn chạy ngầm sau mỗi lần AI chấm và kết quả được lưu lại (trong file xuất dữ liệu là reference_b.csv). Nút này chỉ quyết định bác sĩ có thấy ô kết quả mô hình AI B dưới bảng phân độ hay không.",
  "Model B is not installed on this server.":
    "Máy chủ này chưa cài mô hình AI B.",
  "Now: shown to clinicians.":
    "Hiện tại: bác sĩ ĐANG thấy.",
  "Now: hidden from clinicians.":
    "Hiện tại: đang ẩn với bác sĩ.",
  "Model B's answer for every study it read, for comparison.":
    "Kết quả của mô hình AI B cho mọi ca nó đã đọc, để so sánh.",
  "Previous slice":
    "Lát trước",
  "Next slice":
    "Lát sau",
  "Slice {i} / {n}":
    "Lát {i} / {n}",
  "Zoom in":
    "Phóng to",
  "Zoom out":
    "Thu nhỏ",
  "Brightness":
    "Độ sáng",
  "Contrast":
    "Độ tương phản",
  "Back to the original picture":
    "Trở về ảnh ban đầu",
  "Reset image":
    "Về ảnh gốc",
  "Abnormal findings":
    "Tóm tắt bất thường",
  "Only what is not normal. Click a level to see it on the image.":
    "Chỉ liệt kê những gì không bình thường. Bấm vào một tầng để xem trên ảnh.",
  "Nothing abnormal at any level.":
    "Không thấy bất thường ở tầng nào.",
  "show":
    "xem",
  "Changed by you":
    "Bác sĩ đã sửa",
  "What you changed on this study":
    "Những gì bác sĩ đã sửa ở ca này",
  "Nothing yet — every grade is still the AI's.":
    "Chưa sửa gì, mọi kết quả vẫn là của AI.",
  "Not saved yet — press Save under the table.":
    "Chưa lưu. Bấm Lưu bên dưới bảng.",
  "Changed by you — the AI said: {v}":
    "Bác sĩ đã sửa (AI chấm: {v})",
  "What is this website?":
    "Trang web này dùng để làm gì?",
  "It reads a lumbar spine MRI for you: the AI colours the vertebrae and discs on the image and grades what is abnormal at each disc level (T12–L1 down to L5–S1). You check the result and correct anything it got wrong.":
    "Trang web đọc phim MRI cột sống thắt lưng: AI tô màu các đốt sống, đĩa đệm trên ảnh và chấm mức độ bất thường ở từng tầng đĩa đệm (từ T12–L1 đến L5–S1). Có hai mô hình AI khác nhau (gọi là A và B) cùng đọc mỗi ca, nên kết quả có thể khác nhau. AI đọc trước; bác sĩ xem lại, sửa chỗ AI chấm sai và so sánh hai mô hình.",
  "Press “+ New study”, type a study code and the patient's name, then press “Create”.":
    "Bấm “+ Ca mới”, nhập mã ca và tên bệnh nhân, rồi bấm “Tạo”.",
  "On the new study's row, press “Upload” and choose the scan, compressed into one .zip file.":
    "Ở dòng ca vừa tạo, bấm “Tải lên” và chọn file phim đã nén thành một file .zip.",
  "When the study shows “Ready”, press “Open →”. On the study page press “✨ Run AI grading” at the top right: about 1–2 minutes, press it and leave it to run.":
    "Khi ca hiện “Sẵn sàng”, bấm “Mở →”. Trong trang ca, bấm “✨ Chạy chẩn đoán AI” ở góc trên bên phải: mất khoảng 1–2 phút, cứ bấm rồi để đó chờ.",
  "Look at the result, change any cell that is wrong, and press “Save corrections”.":
    "Xem kết quả, sửa ô nào chưa đúng rồi bấm “Lưu hiệu chỉnh”.",
  "When you are done, press “★ Rate this software” at the top right and answer the short survey (about 5 minutes).":
    "Dùng xong, bấm “★ Đánh giá phần mềm” ở góc trên bên phải và trả lời phiếu đánh giá ngắn (khoảng 5 phút).",
  "Open the study and press “✨ Run AI grading” — about 1–2 minutes. Press it and leave it to run.":
    "Mở ca và bấm “✨ Chạy chẩn đoán AI”. Mất khoảng 1–2 phút, cứ bấm rồi để đó chờ.",
  "Look at the result, correct what is wrong, and press Save.":
    "Xem kết quả, sửa chỗ chưa đúng rồi bấm Lưu.",
  "When you are done, answer the short survey “★ Rate this software”.":
    "Dùng xong, bác sĩ trả lời khảo sát ngắn “★ Đánh giá phần mềm”.",
  "Only sagittal lumbar series are graded. Axial (cross-section, “tra”/“ax”) and coronal (“cor”) series are not graded yet — no need to upload them. A research tool — not a diagnosis.":
    "AI chỉ chấm phim cắt dọc (sagittal) vùng thắt lưng. Phim cắt ngang (axial, tên có “tra” hoặc “ax”) và cắt đứng ngang (coronal, tên có “cor”) chưa được chấm, không cần tải lên. Đây là công cụ nghiên cứu, không thay cho chẩn đoán.",
  "Our model vs model B (same question, 1–5)":
    "Mô hình AI A và mô hình AI B (cùng câu hỏi, thang 1–5)",
  "Question":
    "Câu hỏi",
  "Our model":
    "Mô hình AI A",
  "Model B":
    "Mô hình AI B",
  "Red = the lower-rated model on that question.":
    "Màu đỏ = mô hình bị chấm thấp hơn ở câu đó.",
  "Model B — results to compare":
    "Mô hình AI B: kết quả để đối chiếu",
  "A second AI model, run on the same study. It reads one image (the middle slice, shown here) and answers yes/no for the whole image, not per disc level. The “Model A” column is model A's answer for the same finding: yes if it found it at any level.":
    "Một mô hình AI thứ hai, chạy trên cùng ca. Mô hình này đọc một ảnh (lát giữa, hình bên trái) và trả lời có/không cho cả ảnh, không chia theo tầng đĩa đệm. Cột “Mô hình AI A” là câu trả lời của mô hình AI A cho cùng dấu hiệu: “Có” nếu thấy ở ít nhất một tầng.",
  "Model B: probability":
    "Mô hình AI B: xác suất",
  "Model A":
    "Mô hình AI A",
  "Model A has no matching finding":
    "Mô hình AI A không chấm dấu hiệu này",
  "Model A — abnormality grades":
    "Mô hình AI A: điểm bất thường",
  "Model A — abnormal findings":
    "Mô hình AI A: tóm tắt bất thường",
  "A picture can only be read by model B. Model A needs an MRI series.":
    "Ảnh 2D chỉ mô hình AI B đọc được. Mô hình AI A cần phim MRI.",
  "This study is one picture (PNG/JPG), so model A cannot grade it — it needs an MRI series (DICOM .zip, NIfTI or MHA). Model B's result is below.":
    "Ca này là một ảnh 2D (PNG/JPG) nên mô hình AI A không chấm được. Mô hình AI A cần phim MRI (thư mục DICOM nén .zip, NIfTI hoặc MHA). Kết quả của mô hình AI B ở bên dưới.",
  "This picture is a:":
    "Ảnh này là:",
  "Sagittal (side view)":
    "Cắt dọc (sagittal)",
  "Axial (cross-section)":
    "Cắt ngang (axial)",
  "The uploaded picture":
    "Ảnh đã tải lên",
  "Annular Tear":
    "Rách vòng xơ",
  "Bone Marrow Edema":
    "Phù tuỷ xương",
  "Cauda Equina Compression":
    "Chèn ép chùm đuôi ngựa",
  "Disc Bulge":
    "Phồng đĩa đệm",
  "Disc Degeneration":
    "Thoái hoá đĩa đệm",
  "Facet Joint Pathology":
    "Bệnh lý khớp mặt",
  "Herniation":
    "Thoát vị đĩa đệm",
  "Modic Endplate Changes":
    "Thay đổi Modic",
  "Nerve Root Compression":
    "Chèn ép rễ thần kinh",
  "Schmorl's Node":
    "Nốt Schmorl",
  "Spinal Canal Stenosis":
    "Hẹp ống sống",
  "MRI: DICOM folder as .zip, or .mha / .nii / .nii.gz. Or one picture (.png / .jpg) for model B only.":
    "Phim MRI: thư mục DICOM nén .zip, hoặc file .mha / .nii / .nii.gz. Hoặc một ảnh (.png / .jpg), khi đó chỉ mô hình AI B đọc.",
  "Only have a picture (PNG/JPG), not the scan? Upload it the same way — then only model B reads it.":
    "Chỉ có ảnh chụp (PNG/JPG), không có phim? Vẫn tải lên như trên, khi đó chỉ mô hình AI B đọc ảnh.",
  "Back to the AI's grade":
    "Trả về kết quả AI",
  "Put everything back to the AI's grades":
    "Trả tất cả về kết quả AI",
  "Not saved yet — press Save under the table. Undo (Ctrl+Z) also steps back.":
    "Chưa lưu. Bấm Lưu bên dưới bảng. Nút Hoàn tác (Ctrl+Z) cũng lùi lại từng bước.",
  "This study has results from two AI models:":
    "Hai mô hình AI khác nhau đã cùng đọc phim này, nên kết quả có thể khác nhau. A và B đều là AI; bác sĩ là người kiểm tra:",
  "This study has the AI's results:":
    "Ca này có kết quả của AI:",
  "the coloured structures on the image and the grade table, level by level. You can correct it: change a grade, then Save.":
    "tô màu trên ảnh và chấm điểm từng tầng đĩa đệm. Bác sĩ xem lại, chỗ nào AI A chấm sai thì sửa rồi bấm Lưu.",
  "yes/no for the whole image, for comparison only. It cannot be edited.":
    "một AI khác, chỉ trả lời có/không cho cả ảnh. Dùng để so với AI A, không sửa được.",
  "Steps: 1. check model A against the image and correct what is wrong · 2. compare with model B · 3. answer the survey (★ top right), which asks about each model separately.":
    "Thứ tự: 1. AI đọc phim trước (ca đã có màu là AI đã đọc xong) · 2. bác sĩ xem lại kết quả mô hình AI A, sửa chỗ sai · 3. so với mô hình AI B · 4. trả lời khảo sát (★ góc trên bên phải), chấm riêng từng mô hình AI.",
  "Steps: check the result against the image, correct what is wrong, then answer the survey (★ top right).":
    "Các bước: đối chiếu kết quả với ảnh, sửa chỗ sai, rồi trả lời khảo sát (★ góc trên bên phải).",
  "(editable)":
    "(sửa được)",
  "(not editable)":
    "(chỉ xem)",
  "Only what is not normal. Click a level, or one finding, to go to it in the model A table below — it will flash.":
    "Chỉ liệt kê chỗ bất thường. Bấm vào một tầng (hoặc một dấu hiệu) để đi tới đúng ô đó trong bảng mô hình AI A bên dưới, ô sẽ nhấp nháy.",
  "see in table":
    "xem trong bảng",
  "This study is one picture, so only model B reads it:":
    "Ca này là một ảnh 2D nên chỉ mô hình AI B đọc được:",
  "Model B reads the uploaded picture and answers yes/no for the whole image. Say whether the picture is a side view (sagittal) or a cross-section (axial): model B has a version for each.":
    "Mô hình AI B đọc ảnh đã tải lên và trả lời có/không cho cả ảnh. Bác sĩ chọn ảnh là cắt dọc (sagittal) hay cắt ngang (axial), vì mô hình AI B có bản riêng cho từng loại.",
  "Only the sagittal (side view) lumbar series are needed, T2 first":
    "Chỉ cần phim cắt dọc (sagittal) vùng thắt lưng, ưu tiên T2",
  "— their names usually contain “sag”, e.g. t2_tse_sag, SAG T2, T2 SAG FSE.":
    "(tên chuỗi thường có chữ “sag”, ví dụ t2_tse_sag, SAG T2, T2 SAG FSE).",
  "User guide (PDF)":
    "Tải hướng dẫn sử dụng (PDF)",
  "Click to read":
    "Bấm để xem",
  "Collapse":
    "Thu gọn",
});
