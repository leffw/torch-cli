#!/usr/bin/env python3

from subprocess import Popen, PIPE
from os.path import expanduser, exists
from yaml import safe_load, dump
from os import mkdir, system

import click
import json


path = expanduser('~/.torch')

with open(f'{path}/docker-compose.yaml') as file:
    docker_compose = safe_load(file)


@click.group()
def cli():
    '''Bitcoin & Lightning Container Manager for facilitating development tools.
    '''
    ...


@cli.command()
@click.argument("name")
def create(name: str):
    '''Create a new LND container'''
    if name in docker_compose.get('services').keys():
        raise Exception('Node already exists.')

    with open(f'{path}/config.json') as file:
        ports = [port + 1 for port in json.load(file)["ports"]]

    docker_compose['services'][name] = {
        'image': 'lightninglabs/lnd:v0.12.0-beta',
        'container_name': f'torch.{name}',
        'command': [
            f'--alias={name}',
            '--lnddir=/root/.lnd',
            f'--listen=0.0.0.0:{ports[0]}',

            f'--rpclisten=0.0.0.0:{ports[1]}',
            f'--restlisten=0.0.0.0:{ports[2]}',
            f'--externalip=torch.{name}:{ports[0]}',

            '--bitcoin.node=bitcoind',
            '--bitcoin.active',
            '--bitcoin.regtest',

            '--bitcoind.rpchost=torch.bitcoin',
            '--bitcoind.rpcuser=root',
            '--bitcoind.rpcpass=root',

            f'--bitcoind.zmqpubrawblock=tcp://torch.bitcoin:28332',
            f'--bitcoind.zmqpubrawtx=tcp://torch.bitcoin:28333'
        ],
        'ports': [
            f'{ports[0]}:{ports[0]}',
            f'{ports[1]}:{ports[1]}',
            f'{ports[2]}:{ports[2]}'
        ],
        'volumes': [f'{path}/data/{name}:/root/.lnd'],
        'depends_on': ['bitcoin'],
        'restart': 'always'
    }

    with open(f'{path}/config.json', 'w') as file:
        json.dump({'ports': ports}, file)

    if exists(f'{path}/data/{name}') == False:
        mkdir(f'{path}/data/{name}')

    with open(f'{path}/docker-compose.yaml', 'w') as file:
        dump(docker_compose, file)

    system(
        f'docker-compose -f {path}/docker-compose.yaml down --remove-orphans')
    print(json.dumps(docker_compose['services'][name], indent=3))


@cli.command()
@click.argument('name')
def remove(name: str):
    '''Remove container'''
    if not name in docker_compose.get('services').keys():
        raise Exception('Node does not exist.')

    if name == 'bitcoin':
        raise Exception('It is not possible to remove bitcoin.')
    else:
        system(
            f'docker-compose -f {path}/docker-compose.yaml down --remove-orphans')

    docker_compose['services'].pop(name)
    if exists(f'{path}/data/{name}') == True:
        system(f'sudo rm -rf {path}/data/{name}')

    with open(f'{path}/docker-compose.yaml', 'w') as file:
        dump(docker_compose, file)

    print(f'Node {name} removed.')


@cli.command()
def restart():
    '''Restart containers'''
    system(f'docker-compose -f {path}/docker-compose.yaml restart')


@cli.command()
def start():
    '''Start all containers'''
    system(
        f'docker-compose -f {path}/docker-compose.yaml up -d --remove-orphans')


@cli.command()
def stop():
    '''Stop all containers'''
    system(
        f'docker-compose -f {path}/docker-compose.yaml down --remove-orphans')


@cli.command()
@click.argument("name")
def logs(name: str):
    '''View logs from a container'''
    system(f'docker logs torch.{name}')


def exec_cli(name: str, command: str, interactive=True):
    '''Run Commands in Node Bitcoin / Lnd'''
    if not name in docker_compose.get('services').keys():
        raise Exception('Node does not exist.')

    if name == 'bitcoin':
        command = f'torch.bitcoin bitcoin-cli --regtest {command}'
    else:
        port = docker_compose['services'][name]['ports'][1].split(':')[0]
        command = f'torch.{name} lncli --network regtest --rpcserver=127.0.0.1:{port} --lnddir=/root/.lnd --tlscertpath=/root/.lnd/tls.cert {command}'

    if interactive == True:
        system(f'docker exec -i -t {command}')
    else:
        return json.loads(Popen(f'docker exec -i -t {command}', shell=True, stdout=PIPE).communicate()[0].decode('utf-8'))


@cli.command('exec')
@click.argument('name')
@click.argument('command', nargs=-1)
def rpc_exec(name: str, command: str):
    '''Execute command in node'''
    exec_cli(name, ' '.join(command))


@cli.command()
@click.argument('nblock')
def mining(nblock: int):
    '''Generate new blocks'''
    exec_cli('bitcoin', f'-generate {nblock}')


@cli.command()
@click.argument('address')
@click.argument('amount', type=click.INT)
def faucet(address: str, amount: int):
    '''Send Bitcoin to an address'''
    amount = amount / (10 ** 8)
    exec_cli(
        'bitcoin', f'-named sendtoaddress address={address} amount={amount:.8f} fee_rate=25')


@cli.command()
@click.argument('name')
def config(name: str):
    '''Shows container config'''
    if not name in docker_compose.get('services').keys():
        raise Exception('Node does not exist.')
    else:
        print(json.dumps(docker_compose['services'][name], indent=3))


@cli.command()
def listnodes():
    '''List names of all nodes'''
    print(json.dumps(
        {"nodes": list(docker_compose['services'].keys())}, indent=3))


@cli.command()
@click.argument("node_from")
@click.argument("node_to")
def connect(node_from: str, node_to: str):
    '''Connect to one another using the container name'''
    node_to_info = exec_cli(node_to, 'getinfo', interactive=False)
    node_to_uri = node_to_info['uris'][0]
    exec_cli(node_from, f'connect {node_to_uri}')


@cli.command()
@click.argument("node_from")
@click.argument("node_to")
@click.argument("amount", type=click.INT)
def openchannel(node_from: str, node_to: str, amount: int):
    '''Open a new channel using container name'''
    identity_pubkey = exec_cli(node_to, 'getinfo', interactive=False)[
        "identity_pubkey"]
    exec_cli(node_from, f'openchannel {identity_pubkey} {amount}')
    exec_cli('bitcoin', f'-generate 3')


if __name__ == '__main__':
    cli()
