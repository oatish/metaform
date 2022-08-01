from blocks import (
    Block,
    BlockError,
    _GROUPS,
    _VARIABLE,
    _DATA,
    _MODULE,
    _RESOURCE,
    _OUTPUT,
    _PROPERTY,
)
from typing import Union, Optional
import functools
import os
from argparse import ArgumentParser
from __main__ import __file__ as __script_path__


class DependencyError(Exception):
    """
    Exception to return due to issues resolving dependencies
    """


def resolve_dependencies(
    dependency_map: dict[str, set[str]], base_layer: set[str] = set()
) -> list[set[str]]:
    layers = []
    total_blocks = set(dependency_map.keys())
    while base_layer != total_blocks:
        next_layer = set(
            block
            for block in dependency_map
            if dependency_map[block].issubset(base_layer)
        )
        current_layer = next_layer - base_layer
        layers.append(current_layer)
        base_layer = next_layer
        if not current_layer:
            raise DependencyError(
                "Unable to resolve dependencies, ensure they are consistent and non-circular."
            )
    return layers


class Registry(dict):
    def __init__(self):
        super(Registry, self).__init__()

    def __setitem__(self, block_id: str, block: Block):
        if isinstance(block, Block):
            super(Registry, self).__setitem__(block_id, block)
        return self

    def __getitem__(self, block_id: str) -> Block:
        block = super(Registry, self).get(block_id, None)
        if block:
            return block
        else:
            raise BlockError(f"Block {block_id} is not registered in the registry.")

    def __str__(self):
        return str(list(super(Registry, self).keys()))

    def __repr__(self):
        return self.__str__()


class Group:
    _ignore_duplicates = False

    def __init__(self, group: str, registry: Registry):
        self.group = group
        self.registry = registry
        self.blocks = {}

    def __getitem__(self, block_id: str) -> Block:
        return self.blocks[block_id]

    def _update_tracking_and_return(self, new_block: Block):
        self.blocks[str(new_block)] = new_block
        if (str(new_block) not in self.registry) or self._ignore_duplicates:
            self.registry[str(new_block)] = new_block
        else:
            raise BlockError(
                f"Block {new_block} is already registered in the block registry."
            )
        return new_block

    def __call__(
        self,
        *ids,
        **kwargs: Optional[Union[str, int, float, Block, bool, list, dict]],
    ) -> Block:
        new_block = Block(self.group, *ids, **kwargs)
        return self._update_tracking_and_return(new_block)


class MetaFormer:
    def __init__(
        self,
        registry: Optional[Registry] = None,
        default_name: Optional[str] = None,
        default_isolate: bool = False,
        default_split_out: bool = False,
    ):
        if registry is not None:
            self.registry = registry
        else:
            self.registry = Registry()
        self._create_groups()
        self._mf_dir = os.path.dirname(__script_path__)
        self._mf_path = os.path.realpath(__script_path__)
        self._default_name_arg = (
            default_name
            if default_name
            else os.path.basename(self._mf_path).split(".")[0]
        )
        self._default_isolate_arg = "store_false" if default_isolate else "store_true"
        self._default_split_out_arg = (
            "store_false" if default_split_out else "store_true"
        )
        self._mf_args = self._parse_options()

        # shortened aliases
        self.dat = self.data
        self.res = self.resource
        self.mod = self.module
        self.var = self.variable
        self.pro = self.property

    def _parse_options(self):
        parser = ArgumentParser()
        parser.add_argument("--name", "-n", type=str, default=self._default_name_arg)
        parser.add_argument("--isolate", "-i", action=self._default_isolate_arg)
        parser.add_argument("--split_out", "-s", action=self._default_split_out_arg)
        args = parser.parse_args()
        return args

    def _create_groups(self):
        self.data = Group("data", self.registry)
        self.resource = Group("resource", self.registry)
        self.module = Group("module", self.registry)
        self.variable = Group("variable", self.registry)
        self.property = Group("property", self.registry)
        self.output = Group("output", self.registry)
        return self

    def _clear_registry(self):
        self.registry = Registry()
        return self

    def _collect_dependencies(self) -> dict[str, list[str]]:
        return {
            block_id: {str(dep_block) for dep_block in block.dependencies}
            for block_id, block in self.registry.items()
            if block._group != _PROPERTY
        }

    def _resolve_dependencies(self) -> list[set[str]]:
        return resolve_dependencies(self._collect_dependencies())

    def collect(self) -> list[Block]:
        dependencies = self._resolve_dependencies()
        return functools.reduce(
            lambda m, n: self._sort(m) + self._sort(n), dependencies, []
        )

    def _sort(self, deps: set[str]) -> list[Block]:
        """
        Sort the dependencies putting in the following order:
            VARIABLES -> DATA -> RESOURCES -> MODULES -> OUTPUTS
        """
        deps = [self.registry[str(block_id)] for block_id in deps]
        return (
            list(filter(lambda b: b._group == _VARIABLE, deps))
            + list(filter(lambda b: b._group == _DATA, deps))
            + list(filter(lambda b: b._group == _RESOURCE, deps))
            + list(filter(lambda b: b._group == _MODULE, deps))
            + list(filter(lambda b: b._group == _OUTPUT, deps))
            + list(
                filter(
                    lambda b: b._group
                    not in [_VARIABLE, _DATA, _RESOURCE, _MODULE, _OUTPUT],
                    deps,
                )
            )
        )

    def _write(self):
        """
        Return the contents of the MetaForm object as a string
        """
        return "\n\n".join(block._write() for block in self.collect())

    def build(self):
        """
        Build out the new terraform scripts from the metaform commands
        """
        if self._mf_args.isolate:
            main_path = os.path.join(self._mf_dir, self._mf_args.name)
            os.mkdir(main_path)
            with open(os.path.join(main_path, "main.tf"), "w") as f:
                f.write(self._write())
        else:
            with open(f"{self._mf_args.name}.tf", "w") as f:
                f.write(self._write())
