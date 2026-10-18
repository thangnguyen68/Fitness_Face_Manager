# FaceAccess demo

Ứng dụng quản lý hội viên và kiểm soát ra vào, xây từ `prototype/index.html` và `TÉCHTACK.md`. Giao diện tiếng Việt gồm dashboard, hội viên, đăng ký khuôn mặt, nhật ký và kiosk. Dữ liệu lưu dạng file trong `backend/data/`.

## Chạy trực tiếp bằng CMD trên Windows

Cần cài Python 3.11+ và Node.js 20+. Với nhận diện InsightFace trên Windows, nên dùng Python 3.11 hoặc 3.12 vì Python 3.14 có thể thiếu wheel tương thích.

1. Mở CMD tại thư mục dự án, chạy `setup.cmd` để tạo môi trường Python và cài dependency frontend.
2. Chạy `run.cmd`. Script mở hai cửa sổ CMD cho API và website.
3. Mở `http://localhost:5173`. API docs ở `http://localhost:8000/docs`.
4. Lần chạy đầu tạo `.env` từ `.env.example`. Tài khoản demo: `admin@faceaccess.local` / `Admin@123456`. Hãy đổi mật khẩu và `JWT_SECRET` trong `.env` **trước lần khởi động API đầu tiên** nếu dùng dữ liệu thật. Mật khẩu admin được băm và lưu trong `backend/data/staff_users.json` khi API khởi động lần đầu.

Chế độ **Mô phỏng** vẫn yêu cầu camera và ghi nhật ký với nhãn `Mô phỏng`; ảnh chụp chỉ được kiểm tra rồi bỏ, không lưu. Bộ ONNX mặc định là `buffalo_l`, lưu tại `backend/models/models/buffalo_l/`. Khi khởi động API, nếu thiếu model, ứng dụng dùng file ZIP đã có hoặc tự tải từ InsightFace và hiển thị phần trăm tải trong cửa sổ CMD của API. Lần tải đầu cần Internet; nếu tải thất bại, API báo lỗi và có thể chạy lại sau khi có mạng. Có thể đổi thư mục gốc bằng `INSIGHTFACE_ROOT` và tên bộ bằng `INSIGHTFACE_MODEL`. Kiosk dùng API key trong `.env`; nếu đổi key, tạo `frontend/.env.local` với `VITE_KIOSK_API_KEY` cùng giá trị. Kiểm tra giấy phép model trước khi dùng ngoài mục đích thử nghiệm. Camera trình duyệt chỉ hoạt động tại localhost hoặc HTTPS.

Kiosk tự quét khi mở màn hình, vẽ khung và tên ngay trên camera, hiện số ngày còn lại của gói khi nhận diện được hội viên. Khi không còn mặt trong khung hình, giao diện trở lại “Sẵn sàng nhận diện”. Mỗi lần hội viên xuất hiện liên tục chỉ ghi một dòng nhật ký; phải vắng mặt ba lần quét liên tiếp rồi quay lại mới tạo lượt mới. Đăng ký khuôn mặt tự chụp lần lượt hướng thẳng, trái và phải sau hai lần kiểm tra liên tiếp; người dùng chỉ cần xác nhận đồng ý và lưu.

## Chạy riêng để phát triển

```text
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

```text
cd frontend
npm install
npm run dev
```

Mở `http://localhost:5173`. API docs ở `http://localhost:8000/docs`.

Đây là PoC. Chế độ mô phỏng chỉ dành cho người dùng đã đăng nhập và không được xem là kết quả nhận diện sinh trắc.
