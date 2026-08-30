@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "\\host.lan\Data\wireshark_oracle_statistics_report.ps1" %*
