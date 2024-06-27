#!/bin/bash
####################################################
#Settings
####################################################
ownPid=$$
upPath="~/servers.sh"
upConfPath="~/servers.conf"
if [ -f "/mnt/c/Windows/System32/mstsc.exe" ]
then
  exe="/mnt/c/Windows/System32/mstsc.exe"
  flags="/v:"
else
  exe="rdesktop"
  flags="-n"
fi
depRDP=0
exitTerm=0
multiCon=0

#This is used to attempt to generate a unique port number on each run that is high enough that this script can run without admin
port=`expr $$ + 10000`
menuCom="whiptail" #This value doesn't matter once depcheck runs to see what the end user has installed

###################################################
#Functions
###################################################

checkAppUpdate(){
  echo "**********************"
  bastions=("${bastion[@]}")
  bastion=${bastions[$RANDOM % ${#bastions[@]} ]}
  #Download script from bastion host to tmp directory
  md5=`md5sum $0 |cut -d " " -f 1`
  scp -P $base_port $bastion:$upPath /tmp/
  #has file
  if [ -f "/tmp/servers.sh" ]
  then
    newmd5=`md5sum /tmp/servers.sh |cut -d " " -f 1`
  else
    newmd5=$md5
  fi
  #Compare hashes to see if they are different
  if [ "$newmd5" != "$md5" ]
  then
    mv /tmp/servers.sh $0.tmp
  else
    if [ -f "/tmp/servers.sh" ]
    then
      echo ""
      echo "No Application Update found"
      rm /tmp/servers.sh
    fi
  fi
  #Install new script
  if [ -f "$0.tmp" ]
  then
    echo ""
    echo "Application Update found, applying update"
    rm $0
    mv $0.tmp $0
  fi
  echo "**********************"
}  

checkConfUpdate(){
  echo "**********************"
  bastions=("${bastion[@]}")
  bastion=${bastions[$RANDOM % ${#bastions[@]} ]}
  #Download config from bastion host to tmp directory
  confFile=$(echo $0|rev|cut -c 4-|rev).conf
  confmd5=`md5sum $confFile |cut -d " " -f 1`
  scp -P $base_port $bastion:$upConfPath /tmp/
  #has file
  if [ -f "/tmp/servers.conf" ]
  then
    confnewmd5=`md5sum /tmp/servers.conf |cut -d " " -f 1`
  else
    confnewmd5=$confmd5
  fi
  #Compare hashes to see if they are different
  if [ "$confnewmd5" != "$confmd5" ]
  then
    mv /tmp/servers.conf $confFile.tmp
  else
    if [ -f "/tmp/servers.conf" ]
    then
      echo ""
      echo "No Conf Update found"
      rm /tmp/servers.conf
    fi
  fi
  #Install new script
  if [ -f "$confFile.tmp" ]
  then
    echo ""
    echo "Conf Update found, applying update"
    rm $confFile
    mv $confFile.tmp $confFile
  fi
  echo "**********************"
}

cleanUp(){
  ls -a |grep servers.pid | xargs -I XXX cat XXX|xargs -I xxx kill xxx
  ls -a |grep servers.pid | xargs -I xxx rm xxx
}

settingsFile=$(echo $0|rev|cut -c 4-|rev).conf
if [ -f "$settingsFile" ]
then
  . $settingsFile
    bastions=("${bastion[@]}")
    bastion=${bastions[$RANDOM % ${#bastions[@]} ]} #Randomly select host if there is more than one
    if [ -z "$base_port" ]
    then
	    base_port="22"
    fi
    basTest=`nc -q 0 -w 1 "$bastion" "$base_port" < /dev/null`
    count=0
    while [ -z "$basTest" ]
    do
	echo "$bastion is down trying another random host from the list."
	bastion=${bastions[$RANDOM % ${#bastions[@]} ]} #Randomly select host if there is more than one
	basTest=`nc -q 0 -w 1 "$bastion" "$base_port" < /dev/null`
	((count++))
	if [ $count -gt 5 ]
	then
		echo "Unable to connect to any of the hosts that were tried... Exiting"
		exit
	fi
    done
else
  echo "Enter in the server address of the bastion host:"
  read bastion
  echo \#Bastion Server Address >> $settingsFile
  echo bastion=$bastion >> $settingsFile
  echo "Enter in the server port of the bastion host:"
  read base_port
  echo base_port=$base_port >> $settingsFile
  checkConfUpdate
  checkAppUpdate
  exit
fi

depCheck(){
  dep="Missing dependence:"
  depMissing=0
  if [ `command -v dialog|grep -c dialog` -eq 0 ] #Check is dialog is installed on the machine
  then
    if [ `command -v whiptail|grep -c whiptail` -eq 0 ] #Checks if whiptail is installed on the machine if it doesn't find dialog
    then
      dep="$dep whiptail/dialog"
      depMissing=`expr $depMissing + 1` #Notice that a dependancy is missing.
    else
      menuCom='whiptail'
    fi
  else
    menuCom='dialog'
  fi
  if [ `command -v ssh|grep -c ssh` -eq 0 ]
  then
    dep="$dep ssh" #This makes sure ssh is installed... it should be impossible for it to be missing but just in case...
    depMissing=`expr $depMissing + 1`
  fi
  if [ -f "$exe" ]
  then
    depRDP=1
  fi
  if [ "$depMissing" -gt "0" ]
  then
    echo "$depMissing dependence(s) are missing. The following are missing: $dep"
    checkAppUpdate #Run update check incase the dependency changed after this version had been downloaded.
    exit
  fi
}

openWeb(){
  if [ "$depRDP" -eq "1" ]
  then
    nohup $(sleep 3 && explorer.exe "$1") > /dev/null 2>&1 &
  fi
}

doConnection(){
  case $1 in
    W) #Windows Machines
      ssh $bastion -p $base_port -fL $port:$2:3389 sleep 30  #creates a ssh session forwarding the ports and has a sleep at the end after the person disconnects it automatically closes out the session
      if [ $(ps -ef|grep -c "ssh $bastion -p $base_port -fL $port:$2:3389 sleep 30") -gt 1 ] #check to make sure the ssh session is started before continuing
      then
        if [ $multiCon -eq 0 ]
        then
                echo "The Bastion server name is $name"
                echo "Connected to $2"
                echo ""
                echo "The port is $port"
                echo ""
                echo "Connection started at $(date)"
                $exe $flags localhost:$port & #Starts Remote Desktop connection through the ssh session just created.
          count=1
          mCount=00
          hCount=00
          dCount=00
          while [ $(ps -ef|grep -c "ssh $bastion -p $base_port -fL $port:$2:3389 sleep 30") -gt 1 ]
          do
            sleep 1
            printf "Conection established for $dCount days $hCount:$mCount:$count \r"
            count=`expr $count + 1`
            if [ $count -eq 60 ]
            then
          mCount=`expr $mCount + 1`
          count=0
            fi
            if [ $mCount -eq 60 ]
            then
          hCount=`expr $hCount + 1`
          mCount=0
            fi
            if [ $hCount -eq 24 ]
            then
          dCount=`expr $dCount + 1`
          hCount=0
            fi
          done
        else
                $exe $flags localhost:$port & #Starts Remote Desktop connection through the ssh session just created.
        fi
            else
              echo "Problem establishing connection to Bastion host"
            fi
          ;;
    L) #Linux Machines
      ssh $bastion -p $base_port -fL $port:$2:22 sleep 10 
      if [ $(ps -ef|grep -c "ssh $bastion -p $base_port -fL $port:$2:22 sleep 10") -gt 1 ] #check to make sure the ssh session is started before continuing 
      then
        ssh localhost -p $port -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null #creates an ssh connection without requiring the host key since almost every connection is unique it would never have anything to compare it to
      else
        echo "Problem establishing connection to Bastion host"
      fi
    ;;
    M) #Conenct to Bastion Host
      ssh $bastion -p $base_port 
    ;;
    X) #Sets up a socks connection on port 5222 
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        ssh $bastion -p $base_port -tD 5222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the Proxy on \`tput setaf 2\` $bastion \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 5222 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $bastion -p $base_port -ND 5222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
    ;;
    Z) #Wazuh Web Admin Connection
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        openWeb http://localhost:5601
        ssh $bastion -p $base_port -tL 5601:$2:5601 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 5601 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:5601
        nohup ssh $bastion -p $base_port -NL 5601:$2:5601 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
    ;;
    H) #Wazuh Web Admin Connection
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        openWeb http://localhost:8080
        openWeb https://localhost:8443
        nohup ssh $bastion -p $base_port -NL 8080:$2:80 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        ssh $bastion -p $base_port -tL 8443:$2:443 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8080 \`tput sgr0\` and \`tput setaf 2\` 8443 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:8080
        openWeb https://localhost:8443
        nohup ssh $bastion -p $base_port -NL 8080:$2:80 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        nohup ssh $bastion -p $base_port -NL 8443:$2:443 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
    ;;
    D) #Portainer Connection
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        openWeb http://localhost:9000
        ssh $bastion -p $base_port -tL 9000:$2:9000 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 9000 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $bastion -p $base_port -NL 9000:$2:9000 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
        openWeb http://localhost:9000
      fi
    ;;
    N) #Nesus Web Admin Connection
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        openWeb http://localhost:8000
        nohup ssh $bastion -p $base_port -NL 8834:$2:8834 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        ssh $bastion -p $base_port -tL 8000:$2:8000 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8000 \`tput sgr0\` and \`tput setaf 2\` 8834 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:8000
        nohup ssh $bastion -p $base_port -NL 8834:$2:8834 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        nohup ssh $bastion -p $base_port -NL 8000:$2:8000 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
    ;;
    J) #Connection to forward Tomcat default sites.
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        openWeb http://localhost:8443
        ssh $bastion -p $base_port -tL 8443:$2:8443 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8443 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:8443
        nohup ssh $bastion -p $base_port -NL 8443:$2:8443 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
    ;;
    P) #Connection to allow deploying the websites to the webservers.
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        ssh $bastion -p $base_port -tL 8172:$2:8172 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 8172 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $bastion -p $base_port -NL 8172:$2:8172 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
    ;;
    S) #Sql Server Management Studio Connection Only
      #create the ssh session and keeps it open with a top command.  Without this there wouldn't be enough time to start the application
      if [ $multiCon -eq 0 ]
      then
        ssh $bastion -p $base_port -tL 1433:$2:1433 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` 1433 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        nohup ssh $bastion -p $base_port -NL 1433:$2:1433 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
    ;;
    T) #System Administrator Toolbox
    ssh $bastion -p $base_port -fL $port:$2:5222 sleep 10 
    if [ $(ps -ef|grep -c "ssh $bastion -p $base_port -fL $port:$2:5222 sleep 10") -gt 1 ] #check to make sure the ssh session is started before continuing 
    then
      ssh localhost -p $port -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null #creates an ssh connection without requiring the host key since almost every connection is unique it would never have anything to compare it to
    else
      echo "Problem establishing connection to Bastion host"
    fi
    ;;
    Y) #Shutdown WSL (Windows Sub-system for Linux) after it is shutdown it will come back up once it is attempted to be used again.
      echo WARNING!!! This will close ALL linux sessions and disconnect anything connected through those connections.
      read -p "Are you sure you want to continue? (y/N): " -i "n" wsl_cont
      if [ $wsl_cont == "y" ]; then
        echo "Shutting down WSL... please wait."
        /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe 'wsl --shutdown'
      fi
    ;;
    *) #No canned code was given
    #Attempting to use the code as the port number as both the local port number and the server port number.
      if [ $multiCon -eq 0 ]
      then
        openWeb http://localhost:$1
        ssh $bastion -p $base_port -tL $1:$2:$1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "while [ true ]; do clear; echo The Bastion server name is \`tput setaf 2\` $name \`tput sgr0\`; echo You are connected to the \`tput setaf 2\` $2 \`tput sgr0\`; echo Port being forwarded is \`tput setaf 2\` $1 \`tput sgr0\`; echo The current date and time is \`tput setaf 2\` \`date\` \`tput sgr0\`; echo ; echo Press ctrl+c to exit; sleep 1; done && exit"
      else
        openWeb http://localhost:$1
        nohup ssh $bastion -p $base_port -NL $1:$2:$1 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 > /dev/null &
        echo $! > .$(echo $port)-servers.pid
      fi
  esac
}

OSMenu(){
#Check if RDP is available and show menu accordingly
if [ $1 -eq 0 ]
then
  osMenu=("2" "Linux" "3" "Other" "4" "All" "5" "CLI")
else
  osMenu=("1" "Windows" "2" "Linux" "3" "Other" "4" "All" "5" "CLI")
fi
  osChoice=$($menuCom \
--clear --title "$name Server List" \
--menu "Choose the server type:" 15 30 5 \
${osMenu[@]} \
2>&1 > /dev/tty)
}

showMenu(){
#Generate menu
#D = Portainer Port - port 8172
#H = Website Ports - ports 8080, 8443
#J - Java Web Ports - ports 8443
#L = Linux
#M - Bastion Host
#N = Nesus Port - ports 8834, 8000
#P = Publish using MSDeploy - port 8172
#W = Windows
#S = SQL Server - port 1433
#T = Sysadmin Toolbox
#X = SOCKS Proxy - port 5222
#Y = Shutdown WSL
#Z = Wazuh Port - port 5601

#Based on first menu choice show server list.
if [ $1 -eq 1 ] || [ $1 -eq 4 ]
then
  windows=("${windowsMachines[@]}")
else
  windows=()
fi
if [ $1 -eq 2 ] || [ $1 -eq 4 ]
then
  linux=("${linuxMachines[@]}")
else
  linux=()
fi
if [ $1 -eq 3 ] || [ $1 -eq 4 ]
then
  other=("${otherMachines[@]}")
else
  other=()
fi
menuOptions=("${linux[@]}" "${windows[@]}" "${other[@]}")
OPTION=$($menuCom \
--clear --title "$Name Server List" \
--menu "Choose which server you want to connect to?" 20 60 12 \
"${menuOptions[@]}" \
2>&1 > /dev/tty)
}
###################################################
###################################################
###################################################

###################################################
#Check for command line options
###################################################
while [[ $# -gt 0 ]]
do
  key="$1"
  case $key in
  -x|--exit) #Exit the terminal once you close the script
    exitTerm=1
    shift # past argument
    ;;
  -u|--update) #Update the script only
    checkAppUpdate
    checkConfUpdate
    exit
    ;;
  -m|--multi) #Pushes connections to the background so multiple connections can be established through the same terminal session, this only works on windows hosts
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
###################################################
###################################################
###################################################

depCheck
exitstatus=0
while [  $exitstatus -eq 0 ]; do
  OSMenu $depRDP
  exitstatus=$?
  if [ $exitstatus -ne 0 ]; then
    #Person got here because they canceled the menu
    echo "Take Luck!"
    continue
  fi
  if [ $osChoice -eq 5 ]; then
    bash
    continue
  fi
  showMenu $osChoice
  exitstatus=$?
  if [ $exitstatus = 0 ]; then
    stype=`echo "$OPTION" | cut -d "_" -f 2` #get the type of connection
    ip=`echo "$OPTION" | cut -d "_" -f 1` #get the ip address to connect to
    doConnection $stype $ip #Do the actual connecting
    port=`expr $port + 1`
    if [ $multiCon -eq 0 ]
    then
      exitstatus=1
    fi
    osChoice=5
  else
    exitstatus=0
    continue
  fi
  clear
done
checkConfUpdate
checkAppUpdate
if [ $exitTerm = 1 ] || [ $multiCon = 1 ]
then
  spin='-\|/'
  i=0
  while [ `ps -ef|grep -v grep|grep -c mstsc` -gt 0 ]
  do
    #echo "Waiting for `ps -ef|grep -v grep|grep -c mstsc` connection(s) to end"
    i=$(( (i+1) %4 ))
    printf "  Waiting for $(ps -ef|grep -v grep|grep -c mstsc) connection(s) to end \r${spin:$i:1}"
    sleep .1
  done
  if [ $exitTerm = 1 ]
  then
    cleanUp
    kill -9 $PPID
  else
    cleanUp
  fi
fi