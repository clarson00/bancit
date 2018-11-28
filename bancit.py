import csv
import os.path
import optparse
import sys
import platform
import subprocess
from netmiko import ConnectHandler
import threading
import time
import re
import getpass
import logging


def process_command_line(argv):
    global mode
    global directory
    global dlogin
    global multithread
    global time_wait
    global log_file


    class MyParser(optparse.OptionParser):
        def format_epilog(self, formatter):
            return self.epilog


    usage = '\n%prog list_file <options>\n'
    desc= 'This script accepts a CSV file of devices and commands to send to each device. File can be constructed in Excel as follows: '\
    'Each column in the spreadsheet is a single device. '\
        'The first row should be the hostname.'\
        'The second row should be the IP.'\
        'All subsequent rows in a column will sent to the device as commands.'\
        'Each devices output is logged to a separate file. '\


    parser =MyParser('\n'+usage,description=desc,epilog="""\nExamples:

    'ssh-config.py devices.csv'
    Will open devices.csv and look for a device name in row 1 of each column, an IP address in row 2 of each column, and treat row 3
    and beyond in each column as commands to be executed against the device identified by row 1 and 2. 


    """)


    parser.add_option("-d",
                      action="store", dest="directory",
                      help="Use this directory for output")


    parser.add_option("-m",
                      action="store_true",
                      dest="multithread",
                      help="Multithread configurations. Configurations will be pushed out to all devices at once."
                           "DO NOT use this mode if each device requires a different username or password, or you want to send a configuration then see a "
                           "repsonse then send the next confriguration and see a respone etc.")

    parser.add_option("-l",
                      action="store_true", dest="dlogin",
                      help="Require a seperate login for each device. The default assumes a single username and password across all devices. Cannot be used with -m currently")

    parser.add_option("-t",
                      action="store", dest="time_wait", default=2, type="float",
                      help="Set's a wait time for output after sending all commands to device. For commands that can run long before providing output ie.e wr memory or "
                           "show ip route in routers with long routing tables")


    parser.add_option('-o',
                      type='choice',
                      action='store',
                      dest='mode',
                      metavar="OUTPUT_MODE",
                      choices=['IP', 'NAME',],
                      default='IP',
                      help=' Commands file output naming mode. IP = use IP in filename. NAME = use hostname in filename. Default is to use IP',)


    parser.add_option("-f",
                      action="store_true", dest="fresh_logs",
                      help="Deletes and creates new session log file")



    options, args = parser.parse_args()





    ### cannot current;y run multithreading and indivual logins at the same time
    if options.dlogin and options.multithread:
        print "You cannot have multihread and per device login at the same time!"
        sys.exit()

### set initial options
    dlogin = options.dlogin
    multithread = options.multithread
    time_wait = options.time_wait

    directory = os.getcwd()
    if options.directory != None:
        directory = options.directory
    if not os.path.exists(directory):
        os.makedirs(directory)

    log_file = os.path.join(directory,"bancit_session.log")

    ### set file naming mode
    if options.mode == "IP":
        mode = "IP"
    if options.mode == "NAME":
        mode = "NAME"

    if options.fresh_logs:
        if os.path.exists(log_file):
            os.remove(log_file)




    return options, args


def open_file(args=None):
    # Create empty list
    device=[]
    devices=[]

    #If command line argument not set for file, ask user
    while True:
        if not args:
            file = raw_input("What is the path/filename to the configuration csv file?\n>")
        else:
            file=args[0]
        logging.info("Attempting to open file: %s", file)

        #Open file and transpose list of devices and configuraitons
        try:
            with open(file) as csvfile:
                reader = csv.reader(csvfile, delimiter = ',', quotechar= '|')
                configs = list(reader)
            device = [[i[x].strip() for i in configs if i != " "]for x in range(len(configs[0]))]
            csvfile.close()
            break

        except IOError:
            print "\n* File %s does not exist! Please check and try again!\n" % file
            logging.warning("File %s does not exist!", file)
            continue

    #remove all the blank configuration lines from the final list
    devices=[[x for x in i if x!='']for i in device]
    logging.info("File %s opened with %s columns:", file, len(configs[0]))
    print "\n\nFile %s opened with %s configurations/columns.\n" % (file, len(configs[0]))


    return devices


def is_valid_ip(ip):
    check = False
    a = ip.split('.')

    # print "This is ip in list: %s" % a
    if (len(a) == 4) and (1 <= int(a[0]) <= 223) and (int(a[0]) != 127) and (int(a[0]) != 169 or int(a[1]) != 254) and (0 <= int(a[1]) <= 255 and 0 <= int(a[2]) <= 255 and 0 <= int(a[3]) <= 255):
        check = True
    else:
        check = False

    return check



###### Open SSHv2 connection to devices and run command in command file
def open_ssh_conn(ip):
    logging.info("SSH received job for %s with ip of %s", ip[0],ip[1])
    err=[]
    cisco_xrv = {
         'device_type': 'cisco_ios',
         'ip':   ip[1],
         'username': username,
         'password': password,
         'secret' : password,
         'port': 22,               # there is a firewall performing NAT in front of this device
         'verbose': True,
}

    try:

        session = ConnectHandler(**cisco_xrv)
        session.find_prompt()
        session.enable()
        print "\n\n>>>>>>>>> Device {0} <<<<<<<<<".format(ip[0])
        #Read commands from the list and send to device
        logging.info("Sending commands to %s %s", ip[0],ip[1])
        cmds = ip[2:]
        output = session.send_config_set(cmds)
        #time.sleep(time_wait)
        print output
        print ">>>>>>>>> End <<<<<<<<<\n\n"
        if re.search(r"% ", output) or re.search(r"Bad mask /", output) or re.search(r"IP address conflicts", output):
            errmsg = "Device %s may have errors. Please review the output above or check the implementation logs" % (ip[0])
            print errmsg
            logging.warning(errmsg)
            err.append(errmsg)
            print "\nConfiguration for %s complete with errors " % ip[0]
        else:
            print "\nConfiguration for %s complete" % ip[0]



#log the router output to a file
        if mode =="IP":
            name_of_file = os.path.join(directory,ip[1] + "_"+ "log.txt")
        if mode=="NAME":
            name_of_file = os.path.join(directory,ip[0] + "_"+ "log.txt")
        logging.info("Writing implementation log for %s %s", ip[0],ip[1])
        filer = open( name_of_file , 'w+')
        logging.info("writing file %s", name_of_file)
        filer.write(output)
        filer.close()
        logging.info("Saved file %s ", name_of_file)

#update the session log (TO-DO. Cappture all the lines/copnfigs with errors or any errors and add to sessions log.


        logging.info("SSH session with %s %s closed.", ip[0],ip[1])
        err = [x for x in err if multithread]


    except Exception as e:
        print "*** Operation error: %s\n" % e
        logging.warning("Operation error: %S  on %s %s",e, ip[0],ip[1])

    for x in err:
        print x


    return err

############# Check reachability function #############

def reachable(x):

    print "\n* Checking IP reachability. Please wait...\n"
    check2 = False
    print platform.system()

    for ip in x:

        ip  = ip[1].rstrip('\n')
        if platform.system() == "Windows":
            ping_reply = subprocess.call(['ping', '-n', '2', '-w', '2', ip])

        if platform.system()=="Linux":
            ping_reply = subprocess.call(['ping', '-c', '2', '-w', '2', ip])

        if ping_reply == 0:
            check2 = True
            continue

        elif ping_reply == 2:
            print "\n* No response from device %s." % ip
            logging.warning("No response from device %s", ip)
            check2 = False
            break

        else:
            print "\n\n# # # # # # # # # # # # # # # # # # # # # # # # # # # #\n"
            print "Ping to the following device has FAILED:", ip
            print "Please check reachability or IP and try again"
            print "\n# # # # # # # # # # # # # # # # # # # # # # # # # # # #\n\n\n"
            logging.warning("Ping to the following device has FAILED: %s", ip)

            check2 = False
            sys.exit()

    if check2 == True:
        print '\n\n\n*** All devices are reachable....\n'
        logging.info("All devices are reachable")

############# Mutlithread the task so many devices can be done in parallel #############

def create_threads(configs):
    threads = []
    for ip in configs:
        #ip = ip[1].rstrip("\n")
        th = threading.Thread(target = open_ssh_conn, args = (ip,))   #args is a tuple with a single element
        logging.info("Sending job to device")
        th.start()
        threads.append(th)

    for th in threads:
        th.join()

def revert():
    print "The reversion system is under construction"

############# Single thread the task so devices done in order #############
def create_interactive(configs):
    c=False

    if not dlogin:
        user_creds()



    for count, ip in enumerate(configs, start=1):
        while True:
            print"\n\n"
            print "***********************************************************************"
            print "******       Job %s of %s:  %s at %s       ******" % (count, len(configs),ip[0],ip[1])
            print "***********************************************************************"
            print"\n"
            for cmd in ip[3:]:
                print cmd
            print"\n"
            print "***************************************"
            print "******* End job %s commands set *******" % count
            print "***************************************\n"
            print "Configure device %s at %s with job %s?" % (ip[0],ip[1],count)
            go = raw_input("(c)onfigure, (s)kip, or (q)uit?")
            try:
                if go[:1].lower() == "q":
                    sys.exit()
                elif go[:1].lower() == "s":
                    print "\nskipping Job %s Device %s at %s\n" % (count, ip[0],ip[1])
                    logging.info("User skipped job %s device %s at %s configuration",count,ip[0],ip[1])
                    break

                elif go[:1].lower() =="c":
                    logging.info("Sending job %s to device %s at %s", count,ip[0],ip[1])
                    print "\nSending job to device %s...\n" % ip[0]
                    if dlogin:
                        user_creds()
                    open_ssh_conn(ip)   #args is a tuple with a single element
                    c = True
                    break
                else:
                    pass


            except KeyboardInterrupt:
                print "\n\n* Program aborted by user. Exiting...\n"
                logging.info("Exiting at user request")
                sys.exit()

        if c == True:


            while True:
                v=raw_input("(q)uit, (r)evert configuration, or (n)ext device? ")
                if v[:1] == "q":
                    sys.exit()
                elif v[:1] == "n":
                    break
                elif v[:1] == "r":
                    revert()
                else:
                    pass
        else:
            while True:
                v=raw_input("(q)uit or (n)ext device? ")
                if v[:1] == "q":
                    sys.exit()
                elif v[:1] == "n":
                    break
                elif v[:1] == "r":
                    print "The reversion system is still under construction.."
                else:
                    pass






##### Get user login information
def user_creds():
    global username
    global password

    username = raw_input("username: ")
    password = getpass.getpass("password: ")

    logging.info("Received user credentials for user: %s", username)
    return username,password


##### Review session output information
def logs_review():
    print directory

def main(argv=None):



    ## Read in command line arguments and start logging
    options, args = process_command_line(argv)
    logging.basicConfig(filename=log_file, format='%(levelname)s:%(asctime)s - %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p', level=logging.INFO)
    logging.info('\n')
    logging.info('New session started')
    logging.info('CMD line args: %s', args)
    logging.info('CMD line options: %s', options)
    print "New session started..."
    print "Reading in cmd line options & arguments...\n"

## Maybe inplement a -v or -vv option in the future to show debug prints
#    print "CMD line args: %s" % args
#    print "CMD line options: %s \n" % options
#    open the configuration file

    # Call the open file function to get the file contents and do file checking. assign it to the configs variable
    configs=open_file(args)
    print "Checking for valid IP...\n"
    logging.info('Checking for valid IP')

    # Ensure a valid IP for each row of the configs list
    for ip in configs:
        if is_valid_ip(ip[1]) == True:
            print "%s is a valid IP" % ip[1]
        else:
           print "%s is NOT a valid IP. Please check configs and try again." % ip[1]
           logging.warning("%s is not a valid IP", ip)
           sys.exit()

    # Does user want to check reachability of IP? Is so, call reachable function
    while True:
        do_ping = raw_input("\n\n# Check Reachability via ping? (y)es, (n)o, (q)uit: ")
        try:
            if do_ping[:1].lower() == "y":
                reachable(configs)
                break
            elif do_ping[:1].lower() == "n":
                print "Reachability check skipped\n"
                logging.info("Ping check skipped by user")
                break
            elif do_ping[:1].lower() =="q":
                print "Exiting per user request\n"
                logging.info("Exiting at user request")
                sys.exit()

        except KeyboardInterrupt:
            print "\n\n* Program aborted by user. Exiting...\n"
            logging.info("Exiting at user request")
            sys.exit()


    # check the threading options. If multithreaded, get user credentials and send all configs to threading engine
    #if not multithreaded, call the interactive function. Log the activity
    logging.info("Starting worker threads")
    if options.multithread:
        logging.info("Getting user credentials")
        print "Enter Device(s) credentials:\n"
        user_creds()
        create_threads(configs)
    else:
        create_interactive(configs)

#### Future release - offer option to review session and implementation logs from disk
#
#    review = raw_input("Would you like to review session logs?")
#    files = glob.glob(directory)
#    for f in files:
#        with open(f) as fle:
#            t=fle.read()
#            print t





    logging.info("Session Complete")
    print "\n\n\nSession complete. Thanks for using BANCIT - Bobs Awesome Network Configuration Implementation Tool"
    return 0


if __name__ == "__main__":
    status=main()
    sys.exit(status)
