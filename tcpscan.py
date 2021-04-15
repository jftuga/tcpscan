#!/usr/bin/env python3

"""
tcpscan.py 
-John Taylor

A simple, multi-threaded, cross-platform IPv4 TCP port scanner for Python 3.5

examples
--------
1) python3 tcpscan.py -h
     (help, shows all options)

2) python3 tcpscan.py -v 172.16.51.0/29
    (basic usage, scans 100 of the most common ports)

3) python3 tcpscan.py -p all -v 172.16.51.0/29
    (scan all ports, from 172.16.51.0 to 172.16.51.7)

4) python3 tcpscan.py -v -r 4 -o net.csv 172.16.51.0/26
     (show stats at end, show status every 4 seconds to STDERR, save to CSV file)

5) python3 tcpscan.py -v -r 4 172.16.51.0/24 > net.txt
    (save results to net.txt, show status every 4 seconds to STDERR)
    (useful for large ranges with many open ports)

MIT License Copyright (c) 2018 John Taylor
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

To build a windows executable:
pyinstaller -F --noupx tcpscan.py

"""

import os.path
import sys
import socket
import socketserver
import argparse
import time
import ipaddress
import concurrent.futures
import threading
from collections import defaultdict
from datetime import datetime
from random import shuffle
from queue import Queue

pgm_version = "1.40"

# default maximum number of concurrent threads, changed with -T
max_workers = 100

# default connect timeout when checking a port, changed with -t
connect_timeout_lan = 0.07
connect_timeout_wan = 0.18
connect_timeout = 0

# list of ports to scan if -p is not given on the command line
default_port_list = "20,21,22,23,25,47,53,69,80,110,113,123,135,137,138,139,143,161,179,194,201,311,389,427,443,445,465,500,513,514,515,530,548,554,563,587,593,601,631,636,660,674,691,694,749,751,843,873,901,902,903,987,990,992,993,994,995,1000,1167,1234,1433,1434,1521,1528,1723,1812,1813,2000,2049,2375,2376,2077,2078,2082,2083,2086,2087,2095,2096,2222,2433,2483,2484,2638,3000,3260,3268,3269,3283,3306,3389,3478,3690,4000,5000,5432,5433,6000,6667,7000,8000,8080,8443,8880,8888,9000,9001,9389,9418,9998,27017,27018,27019,28017,32400"

# periodically display runtime stats to STDERR, in seconds
runtime_stats = 0
runtime_stats_last_timestamp = 0
runtime_stats_last_port_count = 0

# initialize variables
active_hosts = defaultdict(list)
hosts_scanned = 0
skipped_hosts = 0
skipped_ports = 0
opened_ports = 0
ports_scanned = 0
skipped_port_list = []
resolve_dns = 0

# if -r invoked to display runtime stats, keep track of the display threads
# so that they can all be cancelled when the port scan is completed
disp_runtime_queue = Queue(0)

# CSV logger for --listen
fp_tcp_listen = False
# file pointer:
# fp_tcp_listen_fp

# save DNS lookups into a dict where key=ip, val=hostname
dns_cache = {}


#############################################################################################

def is_ip_on_lan(ip: str) -> bool:
    """Return true when the given IP is in a IANA IPv4 private range, otherwise false

    Args:
        ip An IPv4 address in dotted-quad notation.

    Returns:
        true or false depending on the value of ip

    """
    return ipaddress.IPv4Address(ip).is_private


#############################################################################################

def get_port_list(ports: str) -> list:
    if ports.find("-") > 0 and ports.find(",") == -1:
        # hyphen-delimited range of ports
        start, end = ports.split("-")
        start = int(start)
        end = int(end)
        if end < start:
            print("\nError: For -p option, ending port is less than starting port\n")
            sys.exit(1)
        if end > 65535:
            print("\nError: For -p option, ending port is greater than 65535\n")
            sys.exit(1)
        port_list = list(range(start, end + 1))
    else:
        # comma separated list of ports, can also include a single port
        port_list = ports.split(",")

    return port_list


#############################################################################################

def scan_one_host(ip: str, ports: str) -> dict:
    """Scan a host for the given open ports.
    
    Args:
        ip: An IPv4 address in dotted-quad notation.

        ports: A list of ports in either range format (x-y) or
            list format (a,b,c,d).

    Returns:
        A dict with key=port number or 0 on error
                    val=True|False  (true=opened;false=closed or error)

    """

    global args, max_workers, connect_timeout, hosts_scanned
    global connect_timeout_lan, connect_timeout_wan

    if ports.find("-") > -1 and ports.find(",") > -1:
        print("\nError: For -p option, port list cannot contain both a port range and list of ports\n")
        sys.exit(1)

    hosts_scanned += 1
    port_list = get_port_list(ports)

    # set the timeout based on lan or wan
    if not connect_timeout:
        connect_timeout = connect_timeout_lan if is_ip_on_lan(ip) else connect_timeout_wan

    all_results = {}
    if args.shuffleports:
        shuffle(port_list)
    with concurrent.futures.ThreadPoolExecutor(max_workers) as executor:
        alpha = {executor.submit(scan_one_port, ip, current_port): current_port for current_port in port_list}
        for future in concurrent.futures.as_completed(alpha):
            if future.done():
                port, is_opened = future.result()
                all_results[port] = is_opened

    return all_results


#############################################################################################

def scan_one_port(ip: str, port: str) -> tuple:
    """Scan the given host for one open port.
    
    Args:
        ip: An IPv4 address in dotted-quad notation.

        port: A TCP port number 1-65535 (as a string).

    Returns:
        Returns (1) port number; (2) True if the port is open, otherwise False

    """

    global args, fp_output, active_hosts, opened_ports, ports_scanned
    global max_workers, connect_timeout_lan, connect_timeout_wan, skipped_port_list, skipped_ports, resolve_dns
    global runtime_stats, runtime_stats_last_timestamp, runtime_stats_last_port_count

    port = int(port)
    if port > 65535:
        print("\nError: Port is greater than 65535\n")
        return 0, False

    if port in skipped_port_list:
        if args.verbose:
            line = "{}\t{}\tport-excluded".format(ip, port)
            print(line)
            if args.output:
                fp_output.write("%s\n" % (line.replace("\t", ",")))
                fp_output.flush()
        skipped_ports += 1
        return 0, False

    try:
        ports_scanned += 1
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(connect_timeout)
        result = sock.connect_ex((ip, port))

        if result == 0:
            valid = True
            opened_ports += 1
            active_hosts[ip].append(port)
            if resolve_dns:
                try:
                    name = socket.gethostbyaddr(ip)
                    name = name[0]
                except:
                    name = ""
                line = "{}\t{}\topen\t{}".format(ip, port, name)
            else:
                line = "{}\t{}\topen".format(ip, port)
            print(line)
            if args.output:
                fp_output.write("%s\n" % (line.replace("\t", ",")))
                fp_output.flush()
        else:
            valid = False
            if args.closed:
                line = "{}\t{}\tclosed".format(ip, port)
                print(line)
                if args.output:
                    fp_output.write("%s\n" % (line.replace("\t", ",")))
                    fp_output.flush()

        sock.close()
        return (port, valid)

    except KeyboardInterrupt:
        print("You pressed Ctrl+C")
        return (0, False)

    except socket.error:
        print("Couldn't connect to server %s on port %s" % (ip, port))
        return (0, False)


#############################################################################################

def disp_runtime():
    """Periodically display number of hosts and ports scanned every N seconds
       where N is given by the -r command line switch

       Returns:
           None
    """
    global ports_scanned, runtime_stats, runtime_stats_last_timestamp, runtime_stats_last_port_count
    global disp_runtime_queue

    t = threading.Timer(runtime_stats, disp_runtime)
    disp_runtime_queue.put(t)
    t.start()

    if not ports_scanned: return

    pps = (ports_scanned - runtime_stats_last_port_count) / runtime_stats
    print("[%s]\thosts:%s\tports:%s\tports/sec:%s" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), hosts_scanned, ports_scanned, int(pps)), file=sys.stderr)
    runtime_stats_last_port_count = ports_scanned


#############################################################################################

def create_skipped_port_list(ports: str) -> None:
    """Create a Python list from the given argument string.
    
    Args:
        ports: A list of ports in either range format (x-y) or
            list format (a,b,c,d).

    Returns:
        Modifies the global skipped_port_list, which is a Python
        list to include all ports that will be excluded from scanning.

    """

    global skipped_port_list

    if ports.find("-") > 0 and ports.find(",") == -1:
        # hypen delimited range of ports
        start, end = ports.split("-")
        start = int(start)
        end = int(end)
        if end < start:
            print("\nError: For -X option, ending port is less than starting port\n")
            sys.exit(1)
        skipped_port_list = list(range(start, end + 1))
    else:
        # comma separated list of ports, can also include a single port
        skipped_port_list = [int(n) for n in ports.split(",")]


#############################################################################################

def tcp_connect_handler(sock: socket.socket, remote: list, server: socketserver.TCPServer):
    global dns_cache, fp_tcp_listen, fp_tcp_listen_fp

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    remote_addr = remote[0]

    if resolve_dns:
        if remote_addr not in dns_cache:
            remote_addr_info = []
            try:
                remote_addr_info = socket.gethostbyaddr(remote_addr)
            except socket.herror:
                pass
            except:
                msg = "\n%s\n%s\n" % (sys.exc_info()[0], sys.exc_info()[1])
                print(msg)

            if len(remote_addr_info) >= 1:
                remote_addr = remote_addr_info[0]
                dns_cache[remote[0]] = remote_addr
        else:
            remote_addr = dns_cache[remote_addr]

    print("[%s] Incoming connection on %s:%s from %s:%s" % (
        now, sock.getsockname()[0], sock.getsockname()[1], remote_addr, remote[1]))

    if fp_tcp_listen:
        fp_tcp_listen_fp.write(
            "%s,%s:%s,%s:%s\n" % (now, sock.getsockname()[0], sock.getsockname()[1], remote_addr, remote[1]))
        fp_tcp_listen_fp.flush()
    sock.close()


#############################################################################################

def tcp_listen(port: int) -> None:
    host = "0.0.0.0"

    print("Listening for incoming TCP connections on %s:%s" % (host, port))
    with socketserver.TCPServer((host, port), tcp_connect_handler) as server:
        server.serve_forever()


#############################################################################################

def tcp_listen_setup(ports: str, output: str) -> None:
    """Instead of scanning ports, listen for incoming connection on a group of ports
       and log them to a CV file

       Args:
            ports: a list of ports, such as 80,443,8080 or 20-25

            output: (optional) a CSV file name
    """
    global fp_tcp_listen_fp

    if output and not os.path.exists(output):
        fp_tcp_listen_fp = open(output, mode="w", encoding="latin-1")
        fp_tcp_listen_fp.write("Timestamp,Local,Remote\n")
        fp_tcp_listen_fp.flush()
    elif output:
        fp_tcp_listen_fp = open(output, mode="a", encoding="latin-1")

    port_list = get_port_list(ports)
    print("\nPress Ctrl-C, Ctrl-\\ or Ctrl-Break to exit.\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers) as executor:
        alpha = {executor.submit(tcp_listen, int(current_port)): current_port for current_port in port_list}
        for future in concurrent.futures.as_completed(alpha):
            pass


#############################################################################################

def main() -> None:
    """Process command-line arguments, scan hosts/ports, print results.

    Returns:
        None

    """

    global args, fp_output, default_port_list
    global max_workers, connect_timeout, connect_timeout_lan, connect_timeout_wan
    global skipped_hosts, skipped_ports, hosts_scanned
    global resolve_dns, runtime_stats, runtime_stats_last_timestamp
    global disp_runtime_queue

    parser = argparse.ArgumentParser(
        description="tcpscan: a simple, multi-threaded, cross-platform IPv4 TCP port scanner",
        epilog="tcpscan version: %s" % (pgm_version))
    parser.add_argument("target", help="e.g. 192.168.1.0/24 192.168.1.100 www.example.com", nargs="?", default=".")
    parser.add_argument("-x", "--skipnetblock", help="skip a sub-netblock, e.g. 192.168.1.96/28")
    parser.add_argument("-X", "--skipports", help="exclude a subset of ports, e.g. 135-139")
    parser.add_argument("-p", "--ports",
                        help="comma separated list or hyphenated range, e.g. 22,80,443,445,515  e.g. 80-515  e.g. all (without -p, the %s most common ports are scanned)" % (
                            len(default_port_list)))
    parser.add_argument("-T", "--threads", help="number of concurrent threads, default: %s" % (max_workers))
    parser.add_argument("-t", "--timeout",
                        help="number of seconds to wait for a connect, default: %s for lan, %s for wan" % (
                            connect_timeout_lan, connect_timeout_wan))
    parser.add_argument("-s", "--shufflehosts", help="randomize the order IPs are scanned", action="store_true")
    parser.add_argument("-S", "--shuffleports", help="randomize the order ports are scanned", action="store_true")
    parser.add_argument("-c", "--closed", help="output ports that are closed", action="store_true")
    parser.add_argument("-o", "--output", help="output to CSV file")
    parser.add_argument("-d", "--dns", help="resolve IPs to host names", action="store_true")
    parser.add_argument("-v", "--verbose", help="output statistics", action="store_true")
    parser.add_argument("-r", "--runtime", help="periodically display runtime stats every RUNTIME seconds to STDERR")
    parser.add_argument("-l", "--loop", help="repeat the port scan LOOP times, 0 for continuous")
    parser.add_argument("-lo", "--loopopen", help="repeat the port scan until all port(s) are open",
                        action="store_true")
    parser.add_argument("-lc", "--loopclose", help="repeat the port scan until all port(s) are closed",
                        action="store_true")
    parser.add_argument("-L", "--listen",
                        help="listen on given TCP port(s) for incoming connection(s) [mutually exclusive; but works with --output and --dns]",
                        action="store_true")

    args = parser.parse_args()

    if args.dns:
        resolve_dns = True

    if args.listen:
        try:
            tcp_listen_setup(args.ports, args.output)
        except:
            msg = "\n%s\n%s\n" % (sys.exc_info()[0], sys.exc_info()[1])
            print(msg)
            sys.exit(1)
        finally:
            sys.exit(0)

    if "." == args.target:
        args.target = "127.0.0.1"
    if args.threads:
        try:
            max_workers = int(args.threads)
        except:
            print("Unable to set thread count to:", args.threads)
            sys.exit(1)
    if args.timeout:
        connect_timeout = float(args.timeout)
    if args.output:
        fp_output = open(args.output, mode="w", encoding="latin-1")
    if args.skipports:
        create_skipped_port_list(args.skipports)
    if args.runtime:
        runtime_stats = int(args.runtime)
        runtime_stats_last_timestamp = int(time.time())
        disp_runtime()
    if args.ports:
        if "all" == args.ports.lower():
            args.ports = "1-65535"

    if args.loopopen or args.loopclose:
        args.loop = "0"

    loop_seconds = int(args.loop) if args.loop else 1

    if args.loopclose:
        loop_seconds = 0

    if 0 == loop_seconds:
        loop_seconds = int(sys.maxsize) - 1

    port_list = args.ports if args.ports else default_port_list
    ip_skiplist = ipaddress.ip_network(args.skipnetblock) if args.skipnetblock else []

    if any(c.isalpha() for c in args.target):
        try:
            ip = socket.gethostbyname(args.target)
            hosts = (ip,)
        except:
            print("Unable to resolve hostname:", args.target)
            sys.exit(1)
    else:
        try:
            tmp = ipaddress.ip_network(args.target)
        except ValueError as err:
            print("Error:", err)
            sys.exit(1)

        hosts = list(tmp.hosts())
        if args.shufflehosts:
            shuffle(hosts)

        if not len(hosts):  # a single ip-address was given on cmd-line
            tmp = args.target.replace("/32", "")
            hosts = (tmp,)

    # all_results and now_all_opened are used when args.loopopen=True
    all_results = {}
    now_all_opened = False
    # now_all_closed is used when args.loopclose=True
    now_all_closed = False

    t1 = datetime.now()
    for loop in range(0, loop_seconds):
        for tmp in hosts:
            my_ip = "%s" % tmp
            if tmp in ip_skiplist:
                if args.verbose:
                    line = "{}\tn/a\thost-excluded".format(my_ip)
                    print(line)
                    if args.output:
                        fp_output.write("%s\n" % (line.replace("\t", ",")))
                        fp_output.flush()
                skipped_hosts += 1
                continue
            try:
                all_results = scan_one_host("%s" % my_ip, port_list)
            except KeyboardInterrupt:
                print("\nYou pressed Ctrl+C")
                break

            if args.loopopen:
                if False not in all_results.values():
                    args.loop = False
                    now_all_opened = True
                    print(chr(7))  # beep

        if now_all_opened:
            print("[%s] completed loops:%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), loop + 1))
            break

        if args.loopclose:
            if True not in all_results.values():
                now_all_closed = True
                break
            else:
                time.sleep(0.70)

        if loop_seconds and args.loop:
            try:
                print("[%s] completed loops:%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), loop + 1))
                print()
                time.sleep(0.70)
            except KeyboardInterrupt:
                print("\nYou pressed Ctrl+C")
                break

    if args.loopclose and now_all_closed:
        if not loop:
            loop += 1
        print("[%s] completed loops:%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), loop))
        print(chr(7))  # beep

    if args.runtime:
        while not disp_runtime_queue.empty():
            t = disp_runtime_queue.get()
            t.cancel()

    if runtime_stats:
        now = int(time.time())
        divisor = now - runtime_stats_last_timestamp
        if not divisor:
            divisor = 1
        pps = (ports_scanned - runtime_stats_last_port_count) / divisor
        print("[%s]\thosts: %s\tports: %s\tports/sec: %s" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), hosts_scanned, ports_scanned, int(pps)), file=sys.stderr)

    if args.verbose:
        print()
        print("Scan Time      : ", datetime.now() - t1)
        print("Active Hosts   : ", len(active_hosts))
        print("Hosts Scanned  : ", hosts_scanned)
        print("Skipped Hosts  : ", skipped_hosts)
        print("Opened Ports   : ", opened_ports)
        print("Skipped Ports  : ", skipped_ports)
        print("Ports Scanned  : ", ports_scanned)
        print("Completed Loops: ", loop + 1)
        print()
    else:
        if not opened_ports:
            print()
            print("Opened Ports : ", opened_ports)
            print("Hosts Scanned: ", hosts_scanned)
            print("Ports Scanned: ", ports_scanned)
            print()

    if args.output:
        fp_output.close()


#############################################################################################

if "__main__" == __name__:
    main()
