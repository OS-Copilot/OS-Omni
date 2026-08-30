@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "\\host.lan\Data\wireshark_oracle_advanced_filter_export.ps1" %*
