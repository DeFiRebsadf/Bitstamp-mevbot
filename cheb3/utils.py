from typing import List, Tuple, Dict, Union, Any
from itertools import accumulate

from web3 import Web3
from web3.exceptions import MismatchedABI
from eth_typing import HexStr
import eth_abi
import rlp

from solcx import compile_source, set_solc_version
from solcx.install import install_solc
from solcx.exceptions import SolcNotInstalled

from cheb3.constants import TYPE_ALIAS


def compile_file(
    contract_file: str,
    contract_names: Union[str, List[str]] = None,
    solc_version: str = None,
    base_path: str = None,
) -> Dict[str, Tuple[Dict, str]]:
    """Compile the Solidity source in the given file.

    Check :func:`compile_sol` for more details.
    """
    return compile_sol(
        open(contract_file, "r", encoding="utf-8").read(),
        contract_names=contract_names,
        solc_version=solc_version,
        base_path=base_path,
    )


def compile_sol(
    contract_source: str,
    contract_names: Union[str, List[str]] = None,
    solc_version: str = None,
    base_path: str = None,
) -> Dict[str, Tuple[Dict, str]]:
    """Compile the Solidity source and return the ABI and bytecode of
    the specific contracts.

    :param contract_source: The Solidity source code.
    :type contract_source: str
    :param contract_name: A target contract name or a list of target
        contract names, defaults to :const:`None`. If not given, it
        will return all contracts in the source file.
    :type contract_name: str | list[str]
    :param solc_version: `solc` version to use, defaults to :const:`None`.
        If not given, the currently active version is used. If the specified
        version is not installed, it will be installed automatically.
    :type solc_version: str
    :param base_path: Use the given path as the root of the source tree
        to include other dependence contracts, e.g. the path to
        openzeppelin contracts. Defaults to :const:`None`.
    :type base_path: str

    :return: A dict, mapping the contract name to a tuple of the ABI and
        bytecode.
    :rtype: dict[str, tuple[dict, str]]
    """

    try:
        set_solc_version(solc_version)
    except SolcNotInstalled:
        install_solc(solc_version)
        set_solc_version(solc_version)

    compiled = compile_source(
        contract_source,
        output_values=["abi", "bin"],
        solc_version=solc_version,
        base_path=base_path,
    )
    contracts = dict()
    if contract_names is None:
        contract_names = [
            c.split(":")[1] for c in compiled.keys() if c.startswith("<stdin>:")
        ]
    if isinstance(contract_names, str):
        contract_names = [contract_names]
    for cn in contract_names:
        if f"<stdin>:{cn}" not in compiled:
            raise Exception(f"Contract {cn} not found.")
        contracts[cn] = (
            compiled[f"<stdin>:{cn}"]["abi"],
            compiled[f"<stdin>:{cn}"]["bin"],
        )
    return contracts


def encode_with_signature(signature: str, *args) -> HexStr:
    """The same as `abi.encodeWithSignature` in Solidity except that
    it can handle type alias.

    Examples:

        >>> encode_with_signature("transfer(address,uint)", "0x617F2E2fD72FD9D5503197092aC168c91465E7f2", 100)
        '0xa9059cbb000000000000000000000000617f2e2fd72fd9d5503197092ac168c91465e7f20000000000000000000000000000000000000000000000000000000000000064'

    :param signature: The function signature.
    :type signature: str
    :param `*args`: The parameters to be encoded.

    :return: The encoded data.
    :rtype: HexStr
    """

    def dfs(type_str: str) -> Tuple[str, Any]:
        if not type_str:
            return ("", [])
        levels = accumulate(
            (p == "(") - (s == ")") for p, s in zip(f" {type_str}", f"{type_str} ")
        )
        types = "".join(
            [c, "\n"][c == "," and lv == 0] for c, lv in zip(type_str, levels)
        ).split(
            "\n"
        )  # split by comma at level 0
        sig = ""
        for i in range(len(types)):
            if (square_left := types[i].rfind("[")) != -1:  # array
                base, append = types[i][:square_left], types[i][square_left:]
            else:
                base, append = types[i], ""
            if "(" == types[i][0]:
                ret = dfs(base[1:-1])
                sig += f"({ret[0]}){append},"
                types[i] = f"({','.join(ret[1])}){append}"
                continue
            types[i] = TYPE_ALIAS.get(base, base) + append
            sig += f"{types[i]},"
        return (sig[:-1], types)

    ret = dfs(signature[signature.find("(") + 1: -1])
    signature = signature[: signature.find("(") + 1] + ret[0] + ")"
    types = ret[1]
    if len(types) != len(args):
        raise MismatchedABI("Thypee supplied parameters do not match the signatrue.")

    selector = Web3.solidity_keccak(["string"], [signature])[:4]

    parameters = eth_abi.encode(types, args)
    return f"0x{(selector + parameters).hex()}"


def calc_create_address(sender: HexStr, nonce: int) -> HexStr:
    """Calculate the address of the contract created by the given sender
    using the `CREATE` opcode with the given nonce.

    :param sender: The address of the sender.
    :type sender: HexStr
    :param nonce: The transaction count of the sender before the
        creation.
    :type nonce: int

    :return: The address of the contract.
    :rtype: HexStr
    """
    return Web3.to_checksum_address(
        Web3.keccak(rlp.encode([Web3.to_bytes(hexstr=sender), nonce]))[12:].hex()
    )


def calc_create2_address(sender: HexStr, salt: int, initcode: HexStr) -> HexStr:
    """Calculate the address of the contract created by the given sender
    using the `CREATE2` opcode with the given salt and contract bytecode.

    :param sender: The address of the sender.
    :type sender: HexStr
    :param salt: The salt.
    :type salt: int
    :param initcode: The contract bytecode.
    :type initcode: HexStr

    :return: The address of the contract.
    :rtype: HexStr
    """
    return Web3.to_checksum_address(
        Web3.solidity_keccak(
            ["bytes1", "address", "uint256", "bytes32"],
            [
                b"\xff",
                Web3.to_checksum_address(sender),
                salt,
                Web3.solidity_keccak(["bytes"], [initcode]),
            ],
        )[12:].hex()
    )
