#!/usr/bin/env bash

# Lệnh này đảm bảo rằng Spleeter đã tải các mô hình cần thiết
# trước khi bot bắt đầu.
spleeter download -p spleeter:2stems

# Chạy bot Python
python bot.py
