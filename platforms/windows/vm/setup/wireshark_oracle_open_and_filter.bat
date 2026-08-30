@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "\\host.lan\Data\wireshark_oracle_open_and_filter.ps1" %*
