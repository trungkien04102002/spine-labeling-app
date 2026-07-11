# Hướng dẫn chạy — spine-labeling-app

Runbook 1 trang. Hai cách chạy: **(A) tất cả trên laptop** và **(B) frontend ở
laptop gọi backend chạy trên máy thuê GPU (Vast.ai)**.

> Chuẩn bị 1 lần: upload folder `spine-vm-upload/` (checkpoint 243MB + vài ảnh
> mẫu) lên Google Drive. `vast_setup.sh` sẽ tự tải về khi dựng máy thuê.

---

## A. Chạy tất cả trên laptop (local)

```bash
cd spine-labeling-app

# lần đầu: cài deps (bỏ qua nếu đã cài)
cd backend && python3 -m venv .venv && source .venv/bin/activate \
  && pip install -r requirements.txt && deactivate && cd ..
cd frontend && npm install && cd ..

# đặt checkpoint: backend/models/weights/phase2_cbam.pth

# trỏ tới TotalSpineSeg CLI (đã cài venv riêng)
export TOTALSPINESEG_BIN=/Users/kienha/totalspineseg/venv/bin/totalspineseg
export SEG_DEVICE=cpu

# chạy cả 2
./run.sh                # mở http://localhost:5173
./run.sh stop           # dừng
./run.sh logs           # xem log
```

Seg trên CPU ~10 phút/ca. Muốn nhanh (~1 phút) thì dùng cách B (GPU).

---

## B. Frontend ở laptop → Backend trên máy thuê GPU (Vast.ai)

### B1. Trên máy thuê (SSH vào)

```bash
cd ~
git clone https://github.com/trungkien04102002/spine-labeling-app.git
cd spine-labeling-app

# dựng mọi thứ + tự tải bundle model từ Drive
./vast_setup.sh
#   nếu báo thiếu checkpoint (file 243MB bị Drive chặn quét virus):
#   → share riêng file phase2_cbam.pth, lấy FILE_ID trong link, rồi:
#   ./vast_setup.sh --gdrive-id <FILE_ID>

# chạy CHỈ backend (đã tự ghi backend/.env: SQLite + SEG_DEVICE=cuda)
./run.sh backend
```

### B2. Trên laptop

```bash
# mở tunnel: cổng 8000 của laptop → backend trên máy thuê
ssh -p <PORT> -L 8000:localhost:8000 root@<HOST>
#   <PORT>, <HOST> lấy ở nút "Connect" của instance Vast

# ở cửa sổ khác trên laptop: chạy CHỈ frontend
cd spine-labeling-app
./run.sh frontend       # VITE_API_URL mặc định = http://localhost:8000 = tunnel
```

Mở **http://localhost:5173** trên laptop. Nhờ tunnel, mọi thứ đều là
`localhost` nên không phải chỉnh CORS gì cả. Frontend ở laptop, còn backend +
GPU chạy trên máy thuê.

> Không muốn dùng tunnel mà expose thẳng? Chạy backend `--host 0.0.0.0`, map cổng
> trên Vast, rồi trên laptop: `VITE_API_URL=http://<host>:<port> ./run.sh frontend`
> và đặt `CORS_ORIGINS=http://localhost:5173` trong `backend/.env` của máy thuê.

---

## Dùng thử

Worklist ban đầu rỗng (dữ liệu không đi kèm code):

1. **+ New study** → nhập Study ID + tên bệnh nhân → Create.
2. Bấm **Upload** → chọn 1 file `.mha` / `.nii.gz`
   (máy thuê: ảnh mẫu đã tải sẵn ở `sample_volumes/`).
3. **Run AI** → chạy segmentation + grading (GPU ~1 phút, CPU ~10 phút).
4. Sửa mask (Edit mask) / sửa mức độ trong bảng → **Save corrections** → **Export**.

---

## Sự cố hay gặp

| Triệu chứng | Cách xử lý |
|---|---|
| Trang 404 / backend không lên | `./run.sh logs`; nếu "Address already in use" → `./run.sh stop` rồi chạy lại |
| Grade rỗng sau Run AI | Thiếu checkpoint — kiểm tra `backend/models/weights/phase2_cbam.pth` |
| Seg báo lỗi CLI | Sai `TOTALSPINESEG_BIN`, hoặc chưa `totalspineseg_init` |
| Máy thuê không có CUDA | Sửa `SEG_DEVICE=cpu` trong `backend/.env` (chậm hơn) |

Chi tiết deploy: [DEPLOY_VAST.md](DEPLOY_VAST.md) · Tổng quan: [README.md](README.md)
