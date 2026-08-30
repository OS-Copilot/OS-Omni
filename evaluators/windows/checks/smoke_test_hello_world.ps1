if (Test-Path 'C:\Temp\helloworld_windows_test.txt') { Get-Content 'C:\Temp\helloworld_windows_test.txt' } else { exit 1 }
