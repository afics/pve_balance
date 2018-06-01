from operator import attrgetter
from helper import get_logger

from model import Migration

logger = get_logger(__name__)


def sort_max_imbalance(hosts):
    """
    Sorts the hosts by memory imbalance and returns the greatest absolute
    imbalance
    """
    hosts.sort(key=attrgetter('memory_imbalance'), reverse=True)
    return max_imbalance(hosts)


def max_imbalance(hosts):
    """
    Given a list sorted by memory imbalance, returns the greatest absolute
    imbalance
    """
    return max((
        abs(hosts[0].memory_imbalance),
        abs(hosts[-1].memory_imbalance),
    ))


def calculate_migrations(hosts, exclude=[], threshold=1024**3):
    migrations = []

    if not hosts:
        return migrations

    target_ratio = sum(host.used_memory for host in hosts)
    target_ratio /= sum(host.memory for host in hosts if host not in exclude)
    logger.debug(
        'Target memory ratio is {:.0%}',
        target_ratio,
    )

    if target_ratio > 0.9:
        logger.warning(
            'Target memory ratio {:.0%} is over 90%',
            target_ratio,
        )

    # Calculate the initial memory imbalance
    for host in hosts:
        if host in exclude:
            # If we want to exclude the host, fake it's target memory
            host.memory_imbalance = 0
        else:
            # Otherwise, aim for same ratio of used memory everywhere
            host.memory_imbalance = target_ratio * host.memory

        host.memory_imbalance -= host.used_memory

    del host

    # Avoid changing the collection outside this function
    hosts = list(hosts)

    while sort_max_imbalance(hosts) > threshold:
        logger.debug(
            'Remaining memory imbalance: {!b}',
            max_imbalance(hosts),
        )

        # Migrate from the most over-staffed to the most under-staffed host
        source_host = hosts[-1]
        target_host = hosts[0]
        logger.debug(
            'Trying migrating from host {} to host {}',
            source_host.name,
            target_host.name,
        )
        for vm in sorted(source_host.vms, key=attrgetter('memory'), reverse=True):
            if vm in (migration.vm for migration in migrations):
                logger.debug(
                    'VM {} is already planned for migration, ignoring it',
                    vm.id,
                )
                continue

            if vm.memory > -source_host.memory_imbalance + threshold:
                logger.debug(
                    "VM {0.id} (memory={0.memory!b}) overshoots source "
                    "host's imbalance of {1.memory_imbalance!b} by more "
                    "than {2!b}",
                    vm, source_host, threshold,
                )
                continue

            if vm.memory > target_host.memory_imbalance + threshold:
                logger.debug(
                    "VM {0.id} (memory={0.memory!b}) overshoots target "
                    "host's imbalance of {1.memory_imbalance!b} by more "
                    "than {2!b}",
                    vm, target_host, threshold,
                )
                if source_host in exclude:
                    logger.info(
                        "Migrating VM {0.id} from host {1.name} to host "
                        "{2.name} despite overshooting memory imbalance by "
                        "{3!b}, because we need to empty {1.name}",
                        vm, source_host, target_host,
                        vm.memory - target_host.memory_imbalance,
                    )
                else:
                    continue

            # This migration seems useful, remember it and update the memory
            # imbalance of the hosts associated
            logger.info(
                "Planning migration of VM {} from host {} to host {}",
                vm.id,
                source_host.name,
                target_host.name,
            )
            migrations.append(Migration(vm, target_host))
            source_host.memory_imbalance += vm.memory
            target_host.memory_imbalance -= vm.memory

            # Break the VM loop to re-order hosts first
            break

        else:
            # If the VM loop terminated without breaking, we didn't plan any
            # migration from the most over-staffed to the most under-staffed
            # host. So apparently, we're done.
            break

    logger.info(
        'Terminating with a remaining memory imbalance of {!b}',
        sort_max_imbalance(hosts),
    )
    for host in exclude:
        if host.memory_imbalance < -threshold:
            logger.warning(
                'Terminating without fully emptying {0.name}!',
                host,
            )

    return migrations