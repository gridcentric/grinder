#!/usr/bin/env python

import os
import sys
import re
import urllib2
import shutil
import subprocess
from cookielib import CookieJar

from config import default_config as config

def install_packages():
    # Save the current working dir
    toplevel_working_dir = os.getcwd()

    print "Setting up staging area"
    # Delete any files from previous runs.
    if os.path.exists(config.package_tmp_dir):
        shutil.rmtree(config.package_tmp_dir)
    # Re-create the staging directory.
    os.makedirs(config.package_tmp_dir)

    cj = CookieJar()
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
    auth_url = "http://%s/j_acegi_security_check?j_username=%s&j_password=%s&remember_me=true" % \
        (config.build_server, config.build_username, config.build_password)
    
    print "Authenticating to build server"
    r = opener.open(auth_url)
    r.close()

    def fetch_package(url, opener, output_file):
        stream = opener.open(url)
        f = open(os.path.join(config.package_tmp_dir, output_file), "w")
        f.write(stream.read())
        stream.close()
        f.close()

    print "Fetching vms packages"

    vms_package_url = "http://%s/job/%s/lastSuccessfulBuild/artifact/*zip*/archive.zip" % \
        (config.build_server, config.vms_project)

    fetch_package(vms_package_url, opener, "archive-vms.zip")

    print "Fetching openstack packages"

    openstack_package_url = "http://%s/job/%s/lastSuccessfulBuild/artifact/*zip*/archive.zip" % \
        (config.build_server, config.openstack_project)

    fetch_package(openstack_package_url, opener, "archive-openstack.zip")

    def install(project_name, project_archive_file, project_package_manifest, pre_install_task=None,
                post_install_task=None):
        print "================== Installing", project_name, "=================="
        print "Extracting archive contents"
        os.chdir(config.package_tmp_dir)

        if os.path.exists("archive"):
            print "Deleting old archive directory found in staging area"
            shutil.rmtree("archive")

        os.system("unzip %s" % project_archive_file)
        os.chdir(os.path.join("archive", "dist_deb"))

        print "Identifying target packages"
        listing = os.listdir(".")
        packages = []

        # Build up the list of (package_name, package_list) tuples.
        for package_name, package_pattern in project_package_manifest:
            packages.append((package_name, 
                             [ p for p in listing if re.match(package_pattern, p) ]))

        # Do a quick sanity test of the list we just built.
        for p in packages:
            name, plist = p
            if len(plist) == 0:
                print "WARNING: no candidate found for package type", name
            elif len(plist) > 1:
                print "Found mulitple matches for package type", name, "selecting", plist[0]

        print "Selected targets:"
        for p in packages:
            name, plist = p
            print "    %s: %s" % (name, plist[0] if len(plist) > 0 else "NOT FOUND")

        def find_packages(pattern, lst):
            return [ pkg for pkg in listing if re.match(pattern, pkg) ]

        if pre_install_task:
            print "Executing pre-install tasks"
            packages = pre_install_task(packages)

        print "Installing targets"
        package_list_incantation = " ".join([ p[0] for _, p in packages if len(p) > 0 ])
        os.system("dpkg -i --force-confold %s" % package_list_incantation)

        # Cleanup
        os.chdir(toplevel_working_dir)
        shutil.rmtree(os.path.join(config.package_tmp_dir, "archive"))

        if post_install_task:
            print "Executing post-install tasks"
            post_install_task(packages)

    def vms_pre_install(packages):
        # Assume vmsfs in fstab. Find the mountpoint.
        mountpoint = None
        f = open("/etc/fstab", "r")
        for l in f.readlines():
            if "vmsfs" in l:
                mountpoint = l.split()[1]
                break
        f.close()

        if mountpoint:
            print "Attempting to umount vmsfs from", mountpoint
            p = subprocess.Popen('umount %s' % mountpoint, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p.wait()
            if p.returncode == 0:
                # Everything is fine, carry on with installation.
                print "Vmsfs successfully unmounted"
                return packages
            else:
                # Either vmsfs is not mounted or its busy. First check if it's mounted
                m = subprocess.Popen(['mount'], stdout=subprocess.PIPE)
                sout, serr = m.communicate()
                if mountpoint in sout:
                    # VMSFS is mounteded and busy, don't attempt to re-install vmsfs.
                    print "Dropping vmsfs package from target list because vmsfs is busy (rc = %d)" % p.returncode
                    return [ (n, p) for n, p in packages if n != "vmsfs" ]
                else:
                    # Vmsfs not mounted. Carry on.
                    return
        else:
            # Can't find mountpoint, assume vmsfs not installed and carry on.
            print "Can't find vmsfs mount point"
            return packages

    def vms_post_install(packages):
        # Figure out if we just installed vmsfs. Return if we didn't.
        installed_vmsfs = False
        for n, _ in packages:
            if n == "vmsfs":
                installed_vmsfs = True
                break

        if not installed_vmsfs:
            print "Not touching vmsfs mount since vmsfs wasn't installed."
            return

        # Assume vmsfs in fstab. Find the mountpoint.
        mountpoint = None
        f = open("/etc/fstab", "r")
        for l in f.readlines():
            if "vmsfs" in l:
                mountpoint = l.split()[1]
                break
        f.close()
        
        print "Mounting vmsfs at", mountpoint
        os.system("mount %s" % mountpoint)

    install("vms", "archive-vms.zip", config.vms_packages, 
            pre_install_task = vms_pre_install,
            post_install_task = vms_post_install)
    
    def openstack_post_install(packages):
        for service in ["nova-compute", "nova-gridcentric"]:
            if os.system("restart %s" % service) != 0:
                os.system("start %s" % service)

    install("openstack", "archive-openstack.zip", config.openstack_packages,
            post_install_task = openstack_post_install)

if __name__ == "__main__":
    install_packages()
