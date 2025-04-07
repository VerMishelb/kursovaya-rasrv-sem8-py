echo Launch "docker-compose up" in %~dp0% if you haven't already. Disable "app".
set KFOLDER=%~dp0%
set PYTHONPATH=%PYTHONPATH%;%KFOLDER%
python "%KFOLDER%/database/init_db.py"
echo simulator.py and main.py will be launched. To cancel, close the window.
pause
start cmd /k python "%KFOLDER%/simulator.py"
start cmd /k python "%KFOLDER%/main.py"
pause