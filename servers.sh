#!/bin/bash
####################################################
# Settings and Environment Detection
####################################################

# Detect if running under WSL by checking /proc/version for "microsoft"
if grep -qi microsoft /proc/version; then
    runningOnWSL=1
else
    runningOnWSL=0
fi

# Save the current process ID
ownPid=$$
# Set remote paths for the script and its configuration file on the bastion host
upPath="~/servers.sh"
upConfPath="~/servers.conf"

# Check if running on Windows (WSL) by verifying existence of mstsc.exe
if [ -f "/mnt/c/Windows/System32/mstsc.exe" ]; then
  # Use Windows Remote Desktop Connection executable and flag
  exe="/mnt/c/Windows/System32/mstsc.exe"
  flags="/v:"
# Otherwise, if running on Linux and the rdesktop tool is available, use it
elif command -v rdesktop >/dev/null 2>&1; then
  exe="rdesktop"
  flags="-n"
else
  # If neither remote desktop client is found, leave these variables empty.
  exe=""
  flags=""
fi

# Flag indicating if a remote desktop client is available (will be set in depCheck)
depRDP=0       
# Flag to determine if the terminal should exit after sessions end
exitTerm=0     
# Flag for allowing multiple simultaneous connections
multiCon=0     

# Generate a unique starting port number using the current PID offset by 10000
port=`expr $$ + 10000`

# Default menu command (will be set later to either 'dialog' or 'whiptail')
menuCom="whiptail"  

####################################################
# Function Definitions
####################################################

# checkAppUpdate: Check for an updated version of the script on the bastion host.
checkAppUpdate(){
  echo "**********************"
  # Randomly select one bastion host from the bastion array
  bastions=("${bastion[@]}")
  bastion=${bastions[$RANDOM % ${#bastions[@]} ]}
  # Compute MD5 hash for the current script file ($0)
  md5=`md5sum $0 | cut -d " " -f 1`
  # Securely copy the remote script from the bastion host to /tmp
  scp -P $base_port $remote_user@$bastion:$upPath /tmp/
  # If the file was copied, compute its MD5 hash; otherwise, keep same hash.
  if [ -f "/tmp/servers.sh" ]; then
    newmd5=`md5sum /tmp/servers.sh | cut -d " " -f 1`
  else
    newmd5=$md5
  fi
  # If the remote script differs from the current one, move it to a temporary file.
  if [ "$newmd5" != "$md5" ]; then
    mv /tmp/servers.sh $0.tmp
  else
    # If no update is found, clean up the temporary file.
    if [ -f "/tmp/servers.sh" ]; then
      echo ""
      echo "No Application Update found"
      rm /tmp/servers.sh
    fi
  fi
  # If an update exists, replace the current script with the updated version.
  if [ -f "$0.tmp" ]; then
    echo ""
    echo "Application Update found, applying update"
    rm $0
    mv $0.tmp $0
  fi
  echo "**********************"
}  

# checkConfUpdate: Check for an updated configuration file on the bastion host.
checkConfUpdate(){
  echo "**********************"
  # Randomly select one bastion host from the bastion array
  bastions=("${bastion[@]}")
  bastion=${bastions[$RANDOM % ${#bastions[@]} ]}
  # Set the local configuration file path
  confFile=$settingsFile
  # Compute the MD5 hash for the local configuration file
  confmd5=`md5sum $confFile | cut -d " " -f 1`
  # Copy the remote configuration file to /tmp
  scp -P $base_port $remote_user@$bastion:$upConfPath /tmp/
  # If the file exists, compute its MD5 hash; otherwise, use the current hash.
  if [ -f "/tmp/servers.conf" ]; then
    confnewmd5=`md5sum /tmp/servers.conf | cut -d " " -f 1`
  else
    confnewmd5=$confmd5
  fi
  # If the hashes differ, move the new config file to a temporary file.
  if [ "$confnewmd5" != "$confmd5" ]; then
    mv /tmp/servers.conf $confFile.tmp
  else
    # If no update is found, notify and remove the temporary file.
    if [ -f "/tmp/servers.conf" ]; then
      echo ""
      echo "No Conf Update found"
      rm /tmp/servers.conf
    fi
  fi
  # If an updated configuration file is found, replace the old one.
  if [ -f "$confFile.tmp" ]; then
    echo ""
    echo "Conf Update found, applying update"
    rm $confFile
    mv $confFile.tmp $confFile
  fi
  echo "**********************"
}

# cleanUp: Kill lingering processes (using PID files) and remove PID files.
cleanUp(){
  ls -a | grep servers.pid | xargs -I XXX cat XXX | xargs -I xxx kill xxx
  ls -a | grep servers.pid | xargs -I xxx rm xxx
}

# customFile: Create or load a custom configuration file with user-specific settings.
customFile(){
  # Determine the custom file name based on the script name.
  oldCustomFile=$(echo $0 | cut -c 3- | rev | cut -c 4- | rev).cust
  if [ -f "$oldCustomFile" ]; then
    mv $oldCustomFile .$oldCustomFile
  fi
  # The custom file is stored as a hidden file in the same directory.
  customFile=./.$(echo $0 | cut -c 3- | rev | cut -c 4- | rev).cust
  if [ -f "$customFile" ]; then
    # If it exists, source it to load variables like remote_user.
    . $customFile
  else
    # Otherwise, prompt the user for the remote username.
    read -p "Enter remote user (Press enter for current user): " remote_user
    remote_user=${remote_user:-`whoami`}
    # Save the input to the custom file.
    echo remote_user=$remote_user > $customFile
  fi
}

# Handle legacy settings file names by renaming old configuration files.
oldSettingsFile=$(echo $0 | cut -c 3- | rev | cut -c 4- | rev).conf
if [ -f "$oldSettingsFile" ]; then
  mv $oldSettingsFile .$oldSettingsFile
fi

# Define the settings file (hidden) based on the script name.
settingsFile=./.$(echo $0 | cut -c 3- | rev | cut -c 4- | rev).conf
if [ -f "$settingsFile" ]; then
  # Source settings file if it exists.
  . $settingsFile
  bastions=("${bastion[@]}")
  # Randomly select a bastion host if multiple are defined.
  bastion=${bastions[$RANDOM % ${#bastions[@]} ]}
  customFile
  # Set default SSH port if not defined.
  if [ -z "$base_port" ]; then
	  base_port="22"
  fi
  # Test connectivity to the bastion host on the defined port.
  basTest=`nc -q 0 -w 1 "$bastion" "$base_port" < /dev/null`
  count=0
  while [ -z "$basTest" ]; do
	  echo "$bastion is down trying another random host from the list."
	  bastion=${bastions[$RANDOM % ${#bastions[@]} ]}
	  basTest=`nc -q 0 -w 1 "$bastion" "$base_port" < /dev/null`
	  ((count++))
	  if [ $count -gt 5 ]; then
		  echo "Unable to connect to any of the hosts that were tried... Exiting"
		  exit
	  fi
  done
else
  # If settings file doesn't exist, prompt for bastion host and port, then create the file.
  echo "Enter in the server address of the bastion host:"
  read bastion
  echo \#Bastion Server Address >> $settingsFile
  echo bastion=$bastion >> $settingsFile
  echo "Enter in the server port of the bastion host:"
  read base_port
  echo base_port=$base_port >> $settingsFile
  customFile
  checkConfUpdate
  checkAppUpdate
  exit
fi

# depCheck: Verify required dependencies (dialog/whiptail, ssh, and remote desktop client).
depCheck(){
  dep="Missing dependence:"
  depMissing=0
  # Check for the dialog tool; if not found, check for whiptail.
  if [ `command -v dialog | grep -c dialog` -eq 0 ]; then
    if [ `command -v whiptail | grep -c whiptail` -eq 0 ]; then
      dep="$dep whiptail/dialog"
      depMissing=`expr $depMissing + 1`
    else
      menuCom='whiptail'
    fi
  else
    menuCom='dialog'
  fi
  # Check for ssh command.
  if [ `command -v ssh | grep -c ssh` -eq 0 ]; then
    dep="$dep ssh"
    depMissing=`expr $depMissing + 1`
  fi
  # Updated remote desktop dependency check:
  if [ "$exe" = "rdesktop" ]; then
      if command -v rdesktop >/dev/null 2>&1; then
          depRDP=1
      fi
  else
      if [ -n "$exe" ] && [ -f "$exe" ]; then
          depRDP=1
      fi
  fi
  # If any dependency is missing, notify the user and exit.
  if [ "$depMissing" -gt "0" ]; then
    echo "$depMissing dependence(s) are missing. The following are missing: $dep"
    checkAppUpdate
    exit
  fi
}

# openWeb: Open a URL using the appropriate command for the environment.
openWeb(){
  if [ "$depRDP" -eq "1" ]; then
    if [ "$runningOnWSL" -eq "1" ]; then
      # On WSL, use explorer.exe to open URLs.
      nohup $(sleep 3 && explorer.exe "$1") > /dev/null 2>&1 &
    else
      # On native Linux, use xdg-open to open the default browser.
      nohup xdg-open "$1" > /dev/null 2>&1 &
    fi
  fi
}

# doConnection: Establish the connection based on the connection type.
doConnection(){
  case $1 in
    B) # Bastion Web Admin: Forward local port 8000 to the bastion host's port 8000.
      if [ $multiCon -eq 0 ]; then
        openWeb http://localhost:8000
        ssh $remote_user@$bastion -p $base_port -tL 8000:localhost:8000 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8000 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:8000
        nohup ssh $remote_user@$bastion -p $base_port -NL 8000:localhost:8000 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    W) # Windows Machines: Forward local port to remote RDP port (3389)
      ssh $remote_user@$bastion -p $base_port -fL $port:$2:3389 sleep 30
      if [ $(ps -ef | grep -c "ssh $remote_user@$bastion -p $base_port -fL $port:$2:3389 sleep 30") -gt 1 ]; then
        if [ $multiCon -eq 0 ]; then
          clear
          echo The Bastion server name is `tput setaf 2`$name `tput sgr0`
          echo The Bastion Host is `tput setaf 2`$bastion `tput sgr0`
          echo Connected to `tput setaf 2`$2 `tput sgr0`
          echo The port is `tput setaf 2`$port `tput sgr0`
          echo Connection started at `tput setaf 2`$(date) `tput sgr0`
          $exe $flags localhost:$port &
          # Display a timer showing how long the connection has been established.
          count=1
          mCount=00
          hCount=00
          dCount=00
          while [ $(ps -ef | grep -c "ssh $remote_user@$bastion -p $base_port -fL $port:$2:3389 sleep 30") -gt 1 ]; do
            sleep 1
            printf "Connection established for `tput setaf 2`$dCount`tput sgr0` days `tput setaf 2`$hCount:$mCount:$count`tput sgr0` \r"
            count=`expr $count + 1`
            if [ $count -eq 60 ]; then
              mCount=`expr $mCount + 1`
              count=0
            fi
            if [ $mCount -eq 60 ]; then
              hCount=`expr $hCount + 1`
              mCount=0
            fi
            if [ $hCount -eq 24 ]; then
              dCount=`expr $dCount + 1`
              hCount=0
            fi
          done
        else
          $exe $flags localhost:$port &
        fi
      else
        echo "Problem establishing connection to Bastion host"
      fi
      ;;
    L) # Linux Machines: Forward local port to remote SSH port (22) and create an SSH session.
      ssh $remote_user@$bastion -p $base_port -fL $port:$2:22 sleep 10 
      if [ $(ps -ef | grep -c "ssh $remote_user@$bastion -p $base_port -fL $port:$2:22 sleep 10") -gt 1 ]; then
        ssh localhost -p $port -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
      else
        echo "Problem establishing connection to Bastion host"
      fi
      ;;
    M) # Connect directly to the Bastion Host via SSH.
      ssh $remote_user@$bastion -p $base_port 
      ;;
    X) # SOCKS Proxy: Set up dynamic port forwarding on port 5222.
      if [ $multiCon -eq 0 ]; then
        ssh $remote_user@$bastion -p $base_port -tD 5222 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the Proxy on \`tput setaf 2\` \$bastion \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 5222 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $remote_user@$bastion -p $base_port -ND 5222 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    Z) # Wazuh Web Admin: Forward local port 5601 to remote.
      if [ $multiCon -eq 0 ]; then
        openWeb http://localhost:5601
        ssh $remote_user@$bastion -p $base_port -tL 5601:$2:5601 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 5601 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:5601
        nohup ssh $remote_user@$bastion -p $base_port -NL 5601:$2:5601 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    H) # Wazuh Web Admin: Forward local ports 8080 and 8443 to remote.
      if [ $multiCon -eq 0 ]; then
        openWeb http://localhost:8080
        openWeb https://localhost:8443
        nohup ssh $remote_user@$bastion -p $base_port -NL 8080:$2:80 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        ssh $remote_user@$bastion -p $base_port -tL 8443:$2:443 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8080 \`tput sgr0\` and \`tput setaf 2\` 8443 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:8080
        openWeb https://localhost:8443
        nohup ssh $remote_user@$bastion -p $base_port -NL 8080:$2:80 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        nohup ssh $remote_user@$bastion -p $base_port -NL 8443:$2:443 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    D) # Portainer Connection: Forward local port 9000.
      if [ $multiCon -eq 0 ]; then
        openWeb http://localhost:9000
        ssh $remote_user@$bastion -p $base_port -tL 9000:$2:9000 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 9000 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $remote_user@$bastion -p $base_port -NL 9000:$2:9000 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
        openWeb http://localhost:9000
      fi
      ;;
    N) # Nessus Web Admin: Forward local ports 8834 and 8000.
      if [ $multiCon -eq 0 ]; then
        openWeb http://localhost:8000
        nohup ssh $remote_user@$bastion -p $base_port -NL 8834:$2:8834 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        ssh $remote_user@$bastion -p $base_port -tL 8000:$2:8000 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8000 \`tput sgr0\` and \`tput setaf 2\` 8834 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:8000
        nohup ssh $remote_user@$bastion -p $base_port -NL 8834:$2:8834 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        nohup ssh $remote_user@$bastion -p $base_port -NL 8000:$2:8000 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    J) # Tomcat Connection: Forward local port 8443.
      if [ $multiCon -eq 0 ]; then
        openWeb http://localhost:8443
        ssh $remote_user@$bastion -p $base_port -tL 8443:$2:8443 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8443 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:8443
        nohup ssh $remote_user@$bastion -p $base_port -NL 8443:$2:8443 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    P) # MSDeploy Connection: Forward local port 8172 for website deployment.
      if [ $multiCon -eq 0 ]; then
        ssh $remote_user@$bastion -p $base_port -tL 8172:$2:8172 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8172 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $remote_user@$bastion -p $base_port -NL 8172:$2:8172 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    S) # SQL Server Management Studio: Forward local port 1433.
      if [ $multiCon -eq 0 ]; then
        ssh $remote_user@$bastion -p $base_port -tL 1433:$2:1433 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 1433 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $remote_user@$bastion -p $base_port -NL 1433:$2:1433 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
      ;;
    T) # Sysadmin Toolbox: Forward local port for toolbox functions (5222).
      ssh $remote_user@$bastion -p $base_port -fL $port:$2:5222 sleep 10 
      if [ $(ps -ef | grep -v grep | grep -c "ssh $remote_user@$bastion -p $base_port -fL $port:$2:5222 sleep 10") -gt 1 ]; then
        ssh localhost -p $port -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
      else
        echo "Problem establishing connection to Bastion host"
      fi
      ;;
    Y) # Shutdown Option: If running on WSL, shut it down; otherwise, indicate it's not applicable.
      if [ "$runningOnWSL" -eq "1" ]; then
        echo "Shutting down WSL... please wait."
        /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe 'wsl --shutdown'
      else
        echo "WSL shutdown function is not available on native Linux."
      fi
      ;;
    *) # Default: Use the provided parameter as the port number for generic connections.
      if [ $multiCon -eq 0 ]; then
        openWeb http://localhost:$1
        ssh $remote_user@$bastion -p $base_port -tL $1:$2:$1 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` \$name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` \$2 \`tput sgr0\`; echo The Bastion Host is \`tput setaf 2\` \$bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` \$1 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:$1
        nohup ssh $remote_user@$bastion -p $base_port -NL $1:$2:$1 \
          -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
          -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
  esac
}

# OSMenu: Display an operating system selection menu.
OSMenu(){
  # If remote desktop is not available (depRDP=0), remove Windows from the menu.
  if [ $depRDP -eq 0 ]; then
    osMenu=("2" "Linux" "3" "Other" "4" "All" "5" "CLI")
  else
    osMenu=("1" "Windows" "2" "Linux" "3" "Other" "4" "All" "5" "CLI")
  fi
  # Display the menu using the chosen menu command.
  osChoice=$($menuCom \
    --clear --title "$name Server List" \
    --menu "Choose the server type:" 15 30 5 \
    ${osMenu[@]} \
    2>&1 > /dev/tty)
}

# showMenu: Display a list of servers based on the selected OS.
showMenu(){
  # Build the server list arrays based on the OS selection.
  if [ $1 -eq 1 ] || [ $1 -eq 4 ]; then
    windows=("${windowsMachines[@]}")
  else
    windows=()
  fi
  if [ $1 -eq 2 ] || [ $1 -eq 4 ]; then
    linux=("${linuxMachines[@]}")
  else
    linux=()
  fi
  if [ $1 -eq 3 ] || [ $1 -eq 4 ]; then
    other=("${otherMachines[@]}")
  else
    other=()
  fi
  # Combine the arrays into one menu option list.
  menuOptions=("${linux[@]}" "${windows[@]}" "${other[@]}")
  # Display the server list menu.
  OPTION=$($menuCom \
    --clear --title "$Name Server List" \
    --menu "Choose which server you want to connect to?" 20 60 12 \
    "${menuOptions[@]}" \
    2>&1 > /dev/tty)
}

####################################################
# Process Command Line Options
####################################################
while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    -x|--exit)
      # Set the flag to exit the terminal after sessions.
      exitTerm=1
      shift
      ;;
    -u|--update)
      # Only check for updates and exit.
      checkAppUpdate
      checkConfUpdate
      exit
      ;;
    -m|--multi)
      # Allow multiple simultaneous connections.
      multiCon=1
      shift
      ;;
    *)
      echo "Usage: $0 [-x] [-u] [-m]

-m | --multi     Allows you to connect to multiple machines through one terminal window (Windows Hosts Only)
-x | --exit      Exit the terminal window when done
-u | --update     Check for an update only then exit"
      exit 1
      ;;
  esac
done

####################################################
# Main Execution: Dependency Check and Connection Loop
####################################################
# Verify dependencies
depCheck
exitstatus=0
while [ $exitstatus -eq 0 ]; do
  # Display OS selection menu
  OSMenu $depRDP
  exitstatus=$?
  if [ $exitstatus -ne 0 ]; then
    echo "Take Luck!"
    continue
  fi
  # If CLI is selected, drop to bash shell.
  if [ $osChoice -eq 5 ]; then
    bash
    continue
  fi
  # Display the server list menu
  showMenu $osChoice
  exitstatus=$?
  if [ $exitstatus = 0 ]; then
    # Parse the selected option to extract the connection type and IP address.
    stype=`echo "$OPTION" | cut -d "_" -f 2`
    ip=`echo "$OPTION" | cut -d "_" -f 1`
    # Establish the connection
    doConnection $stype $ip
    # Increment port for the next connection
    port=`expr $port + 1`
    if [ $multiCon -eq 0 ]; then
      exitstatus=1
    fi
    osChoice=5
  else
    exitstatus=0
    continue
  fi
  clear
done
# After the connection loop, check for configuration and script updates.
checkConfUpdate
checkAppUpdate
# If the exit flag is set or multiple connections were allowed, wait for remote desktop sessions to end and clean up.
if [ $exitTerm = 1 ] || [ $multiCon = 1 ]; then
  spin='-\|/'
  i=0
  while [ `ps -ef | grep -v grep | grep -c mstsc` -gt 0 ]; do
    i=$(( (i+1) % 4 ))
    printf "  Waiting for $(ps -ef | grep -v grep | grep -c mstsc) connection(s) to end \r${spin:$i:1}"
    sleep .1
  done
  if [ $exitTerm = 1 ]; then
    cleanUp
    kill -9 $PPID
  else
    cleanUp
  fi
fi
