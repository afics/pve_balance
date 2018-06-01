#! /usr/bin/env python3

import logging
from time import sleep

from proxmoxer import ProxmoxAPI

from model import Host, VM
from algorithm import calculate_migrations
from helper import get_logger


logger = get_logger(__name__)


def get_task(proxmox, upid):
    for task in proxmox.cluster.tasks.get():
        if task['upid'] == upid:
            return task


def main(pve_config, dry=False, exclude_names=[]):
    proxmox = ProxmoxAPI(**pve_config)

    hosts = []
    exclude = []

    for node in proxmox.nodes.get():
        vms = []
        for vm in proxmox.nodes(node['node']).qemu.get():
            vms.append(VM(
                id=vm['vmid'],
                used_memory=vm['mem'],
                total_memory=vm['maxmem'],
                host=node['node'],
            ))
        hosts.append(Host(
            name=node['node'],
            used_memory=node['mem'],
            total_memory=node['maxmem'],
            vms=vms,
        ))
        if node['node'] in exclude_names:
            exclude.append(hosts[-1])

    for migration in calculate_migrations(hosts, exclude):
        logger.info(
            "Migrating VM {0.vm.id} ({0.vm.used_memory!b}) from host "
            "{0.vm.host} to host {0.target_host.name}.",
            migration,
        )

        if dry:
            continue

        upid = proxmox.nodes(migration.vm.host).qemu(migration.vm.id).migrate.post(
            target=migration.target_host.name,
            online=1,
        )

        logger.info("Waiting for completion of task {}", upid)

        while "endtime" not in get_task(proxmox, upid):
            sleep(1)


if __name__ == '__main__':
    from configparser import ConfigParser
    from argparse import ArgumentParser

    config = ConfigParser()
    config.read('config.ini')

    parser = ArgumentParser(
        description='Balance VMs in a Proxmox Virtual Environment cluster.'
    )
    parser.add_argument('host')
    parser.add_argument('--loglevel', metavar="INFO", default='info')
    parser.add_argument('--dry', action='store_true')
    parser.add_argument('--exclude', action='append')
    args = parser.parse_args()

    config['pve']['host'] = args.host
    logging.basicConfig(level=getattr(logging, args.loglevel.upper()))

    main(config['pve'], dry=args.dry, exclude_names=args.exclude)
