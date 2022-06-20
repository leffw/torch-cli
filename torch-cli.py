#!/usr/bin/env python3

from subprocess import Popen, PIPE
from os.path import expanduser, exists
from yaml import safe_load, dump
from os import mkdir, system

import requests
import lnurl
import click
import json

path = expanduser('~/.torch')

with open(f'{path}/docker-compose.yaml') as file:
    docker_compose = safe_load(file)

def exec_cli(name: str, command: str, interactive=True, stdin=False):
    '''Run Commands in Node Bitcoin / Lnd'''
    if not name in docker_compose.get('services').keys():
        raise Exception('Node does not exist.')

    if name == 'bitcoin':
        command = f'bitcoin-cli --regtest {command}'
    else:
        command = command.split("|")
        if len(command) == 1:
            command = ["", command[0]]

        port = docker_compose['services'][name]['ports'][1].split(':')[0]        
        command = (command[0] + "| " if (stdin == True) else "") + \
            f'lncli --network regtest --rpcserver=127.0.0.1:{port} --lnddir=/root/.lnd --tlscertpath=/root/.lnd/tls.cert {command[1]}'
    
    if interactive == True:
        if stdin == True:
            system(f'docker exec -i -t torch.{name} sh -c "{command}"')
        else:
            system(f'docker exec -i -t torch.{name} {command}')
    else:
        execute = Popen(f'docker exec -i torch.{name} sh -c "{command}"', shell=True, stdout=PIPE).communicate()[0].decode('utf-8')
        try:
            return json.loads(execute)
        except:
            return execute


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

    system(f'docker-compose -f {path}/docker-compose.yaml down --remove-orphans')
    system(f'docker-compose -f {path}/docker-compose.yaml up -d --remove-orphans')
    print(f'Node {name} create.')


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
    system(f'docker-compose -f {path}/docker-compose.yaml up -d --remove-orphans')


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


@cli.command()
@click.argument("node")
@click.argument("password")
@click.option("--all", is_flag=True)
def unlock(password: str, node: str, all: str):
    '''Unlock nodes.'''
    if (all == True):
        nodes = list(docker_compose['services'].keys())
        for alias in nodes:
            if alias == "bitcoin":
                continue
            exec_cli(alias, f'echo {password} | unlock --stdin', interactive=True, stdin=True)
    else:
        exec_cli(node, f'echo {password} | unlock --stdin', stdin=True)

@cli.command()
@click.argument("node")
@click.argument("lnurl_code")
@click.option("--amount")
def paylnurl(node: str, lnurl_code: str, amount: int):
    get_data_pay = requests.get(str(lnurl.lnurl_decode(lnurl_code))).json()
    if (get_data_pay["tag"] != "payRequest"):
        raise Exception("Not is payRequest.")
    elif (amount != None) and (amount > get_data_pay["maxSendable"] or amount < get_data_pay["minSendable"]):
        raise Exception("Value is invalid.")
    else:
        print(json.dumps(get_data_pay, indent=3))

    if (amount == None):
        amount = input("\nEnter the amount you want to pay: ")
    
    get_invoice = requests.get(get_data_pay["callback"], params={"amount": amount}).json()
    print(json.dumps(get_invoice, indent=3))
    exec_cli(node, f'payinvoice %s' % (get_invoice["pr"]))

if __name__ == '__main__':
    cli()
