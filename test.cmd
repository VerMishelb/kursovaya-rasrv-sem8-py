set TESTVAR=w t f
echo %TESTVAR%
start cmd /k "echo %TESTVAR%" & "set" & "pause"
pause