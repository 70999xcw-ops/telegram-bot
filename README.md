# AttendanceBot Shift Reset DailyReport NoEarly

Dựa trên bản AttendanceBot_ShiftReset_DailyReport.

## Đã chỉnh

### Giới hạn thời gian
- 🍚 吃饭 / Meal: 30 phút
- 🚻 上厕所 / Toilet: 15 phút
- 🚬 抽烟 / Smoke: 15 phút
- 📌 其他 / Other: 20 phút

### Cảnh báo
- Không báo trước 3 phút nữa.
- Đến đúng giới hạn thời gian mới gửi: 🚨 超时提醒
- Gửi tổng cộng 3 lần.

### Báo cáo tự động
Mỗi ngày **23:55 北京时间**, bot tự gửi:

📊 每日考勤统计

đến ADMIN_IDS.

## Railway Variables

BOT_TOKEN=token bot
ADMIN_IDS=ID admin
TZ=Asia/Shanghai
