"""This file is part of DING0, the DIstribution Network GeneratOr.
DING0 is a tool to generate synthetic medium and low voltage power
distribution grids based on open data.

It is developed in the project open_eGo: https://openegoproject.wordpress.com

DING0 lives at github: https://github.com/openego/ding0/
The documentation is available on RTD: http://ding0.readthedocs.io"""

__copyright__  = "Reiner Lemoine Institut gGmbH"
__license__    = "GNU Affero General Public License Version 3 (AGPL-3.0)"
__url__        = "https://github.com/openego/ding0/blob/master/LICENSE"
__author__     = "nesnoj, gplssm"


import ding0

from ding0.tools import config as cfg_ding0
from ding0.tools.tools import merge_two_dicts
from ding0.core.network.stations import LVStationDing0, MVStationDing0
from ding0.core.network import LoadDing0, CircuitBreakerDing0, GeneratorDing0, GeneratorFluctuatingDing0
from ding0.core import MVCableDistributorDing0
from ding0.core.structure.regions import LVLoadAreaCentreDing0
from ding0.core.powerflow import q_sign
from ding0.core.network.cable_distributors import LVCableDistributorDing0
from ding0.core import network as ding0_nw

from geoalchemy2.shape import from_shape
from math import tan, acos, pi, sqrt
from pandas import Series, DataFrame, DatetimeIndex
from pypsa.io import import_series_from_dataframe
from pypsa import Network
from shapely.geometry import Point

from datetime import datetime
import sys
import os
import logging
import pandas as pd
import numpy as np

if not 'READTHEDOCS' in os.environ:
    from shapely.geometry import LineString

logger = logging.getLogger('ding0')


def export_to_dir(network, export_dir):
    """
    Exports PyPSA network as CSV files to directory

    Parameters
    ----------
        network: :pypsa:pypsa.Network
        export_dir: :obj:`str`
            Sub-directory in output/debug/grid/
            where csv Files of PyPSA network are exported to.
    """

    package_path = ding0.__path__[0]

    network.export_to_csv_folder(os.path.join(package_path,
                                              'output',
                                              'debug',
                                              'grid',
                                              export_dir))


def nodes_to_dict_of_dataframes(grid, nodes, lv_transformer=True):
    """
    Creates dictionary of dataframes containing grid

    Parameters
    ----------
    grid: ding0.MVGridDing0
    nodes: :obj:`list` of ding0 grid components objects
        Nodes of the grid graph
    lv_transformer: bool, True
        Toggle transformer representation in power flow analysis

    Returns:
    components: dict of :pandas:`pandas.DataFrame<dataframe>`
        DataFrames contain components attributes. Dict is keyed by components
        type
    components_data: dict of :pandas:`pandas.DataFrame<dataframe>`
        DataFrame containing components time-varying data
    """
    generator_instances = [MVStationDing0, GeneratorDing0]
    # TODO: MVStationDing0 has a slack generator

    cos_phi_load = cfg_ding0.get('assumptions', 'cos_phi_load')
    cos_phi_load_mode = cfg_ding0.get('assumptions', 'cos_phi_load_mode')
    cos_phi_feedin = cfg_ding0.get('assumptions', 'cos_phi_gen')
    cos_phi_feedin_mode = cfg_ding0.get('assumptions', 'cos_phi_gen_mode')
    srid = int(cfg_ding0.get('geo', 'srid'))

    load_in_generation_case = cfg_ding0.get('assumptions',
                                            'load_in_generation_case')
    generation_in_load_case = cfg_ding0.get('assumptions',
                                            'generation_in_load_case')

    Q_factor_load = q_sign(cos_phi_load_mode, 'load') * tan(acos(cos_phi_load))
    Q_factor_generation = q_sign(cos_phi_feedin_mode, 'generator') * tan(acos(cos_phi_feedin))

    voltage_set_slack = cfg_ding0.get("mv_routing_tech_constraints",
                                      "mv_station_v_level_operation")

    kw2mw = 1e-3

    # define dictionaries
    buses = {'bus_id': [], 'v_nom': [], 'geom': [], 'grid_id': []}
    bus_v_mag_set = {'bus_id': [], 'temp_id': [], 'v_mag_pu_set': [],
                     'grid_id': []}
    generator = {'generator_id': [], 'bus': [], 'control': [], 'grid_id': [],
                 'p_nom': []}
    generator_pq_set = {'generator_id': [], 'temp_id': [], 'p_set': [],
                        'grid_id': [], 'q_set': []}
    load = {'load_id': [], 'bus': [], 'grid_id': []}
    load_pq_set = {'load_id': [], 'temp_id': [], 'p_set': [],
                   'grid_id': [], 'q_set': []}

    # # TODO: consider other implications of `lv_transformer is True`
    # if lv_transformer is True:
    #     bus_instances.append(Transformer)

    # # TODO: only for debugging, remove afterwards
    # import csv
    # nodeslist = sorted([node.__repr__() for node in nodes
    #                     if node not in grid.graph_isolated_nodes()])
    # with open('/home/guido/ding0_debug/nodes_via_dataframe.csv', 'w', newline='') as csvfile:
    #     writer = csv.writer(csvfile, delimiter='\n')
    #     writer.writerow(nodeslist)

    for node in nodes:
        if node not in grid.graph_isolated_nodes():
            # buses only
            if isinstance(node, MVCableDistributorDing0):
                buses['bus_id'].append(node.pypsa_bus_id)
                buses['v_nom'].append(grid.v_level)
                buses['geom'].append(from_shape(node.geo_data, srid=srid))
                buses['grid_id'].append(grid.id_db)

                bus_v_mag_set['bus_id'].append(node.pypsa_bus_id)
                bus_v_mag_set['temp_id'].append(1)
                bus_v_mag_set['v_mag_pu_set'].append([1, 1])
                bus_v_mag_set['grid_id'].append(grid.id_db)

            # bus + generator
            elif isinstance(node, tuple(generator_instances)):
                # slack generator
                if isinstance(node, MVStationDing0):
                    logger.info('Only MV side bus of MVStation will be added.')
                    generator['generator_id'].append(
                        '_'.join(['MV', str(grid.id_db), 'slack']))
                    generator['control'].append('Slack')
                    generator['p_nom'].append(0)
                    bus_v_mag_set['v_mag_pu_set'].append(
                        [voltage_set_slack, voltage_set_slack])

                # other generators
                if isinstance(node, GeneratorDing0):
                    generator['generator_id'].append('_'.join(
                        ['MV', str(grid.id_db), 'gen', str(node.id_db)]))
                    generator['control'].append('PQ')
                    generator['p_nom'].append(node.capacity * node.capacity_factor)

                    generator_pq_set['generator_id'].append('_'.join(
                        ['MV', str(grid.id_db), 'gen', str(node.id_db)]))
                    generator_pq_set['temp_id'].append(1)
                    generator_pq_set['p_set'].append(
                        [node.capacity * node.capacity_factor * kw2mw * generation_in_load_case,
                         node.capacity * node.capacity_factor * kw2mw])
                    generator_pq_set['q_set'].append(
                        [node.capacity * node.capacity_factor * kw2mw * Q_factor_generation * generation_in_load_case,
                         node.capacity * node.capacity_factor * kw2mw * Q_factor_generation])
                    generator_pq_set['grid_id'].append(grid.id_db)
                    bus_v_mag_set['v_mag_pu_set'].append([1, 1])

                buses['bus_id'].append(node.pypsa_bus_id)
                buses['v_nom'].append(grid.v_level)
                buses['geom'].append(from_shape(node.geo_data, srid=srid))
                buses['grid_id'].append(grid.id_db)

                bus_v_mag_set['bus_id'].append(node.pypsa_bus_id)
                bus_v_mag_set['temp_id'].append(1)
                bus_v_mag_set['grid_id'].append(grid.id_db)

                generator['grid_id'].append(grid.id_db)
                generator['bus'].append(node.pypsa_bus_id)


            # aggregated load at hv/mv substation
            elif isinstance(node, LVLoadAreaCentreDing0):
                load['load_id'].append(node.pypsa_bus_id)
                load['bus'].append('_'.join(['HV', str(grid.id_db), 'trd']))
                load['grid_id'].append(grid.id_db)

                load_pq_set['load_id'].append(node.pypsa_bus_id)
                load_pq_set['temp_id'].append(1)
                load_pq_set['p_set'].append(
                    [node.lv_load_area.peak_load * kw2mw,
                     node.lv_load_area.peak_load * kw2mw * load_in_generation_case])
                load_pq_set['q_set'].append(
                    [node.lv_load_area.peak_load * kw2mw * Q_factor_load,
                     node.lv_load_area.peak_load * kw2mw * Q_factor_load * load_in_generation_case])
                load_pq_set['grid_id'].append(grid.id_db)

                # generator representing generation capacity of aggregate LA
                # analogously to load, generation is connected directly to
                # HV-MV substation
                generator['generator_id'].append('_'.join(
                    ['MV', str(grid.id_db), 'lcg', str(node.id_db)]))
                generator['control'].append('PQ')
                generator['p_nom'].append(node.lv_load_area.peak_generation)
                generator['grid_id'].append(grid.id_db)
                generator['bus'].append('_'.join(['HV', str(grid.id_db), 'trd']))

                generator_pq_set['generator_id'].append('_'.join(
                    ['MV', str(grid.id_db), 'lcg', str(node.id_db)]))
                generator_pq_set['temp_id'].append(1)
                generator_pq_set['p_set'].append(
                    [node.lv_load_area.peak_generation * kw2mw * generation_in_load_case,
                     node.lv_load_area.peak_generation * kw2mw])
                generator_pq_set['q_set'].append(
                    [node.lv_load_area.peak_generation * kw2mw * Q_factor_generation * generation_in_load_case,
                     node.lv_load_area.peak_generation * kw2mw * Q_factor_generation])
                generator_pq_set['grid_id'].append(grid.id_db)

            # bus + aggregate load of lv grids (at mv/ls substation)
            elif isinstance(node, LVStationDing0):
                # Aggregated load representing load in LV grid
                load['load_id'].append(
                    '_'.join(['MV', str(grid.id_db), 'loa', str(node.id_db)]))
                load['bus'].append(node.pypsa_bus_id)
                load['grid_id'].append(grid.id_db)

                load_pq_set['load_id'].append(
                    '_'.join(['MV', str(grid.id_db), 'loa', str(node.id_db)]))
                load_pq_set['temp_id'].append(1)
                load_pq_set['p_set'].append(
                    [node.peak_load * kw2mw,
                     node.peak_load * kw2mw * load_in_generation_case])
                load_pq_set['q_set'].append(
                    [node.peak_load * kw2mw * Q_factor_load,
                     node.peak_load * kw2mw * Q_factor_load * load_in_generation_case])
                load_pq_set['grid_id'].append(grid.id_db)

                # bus at primary MV-LV transformer side
                buses['bus_id'].append(node.pypsa_bus_id)
                buses['v_nom'].append(grid.v_level)
                buses['geom'].append(from_shape(node.geo_data, srid=srid))
                buses['grid_id'].append(grid.id_db)

                bus_v_mag_set['bus_id'].append(node.pypsa_bus_id)
                bus_v_mag_set['temp_id'].append(1)
                bus_v_mag_set['v_mag_pu_set'].append([1, 1])
                bus_v_mag_set['grid_id'].append(grid.id_db)

                # generator representing generation capacity in LV grid
                generator['generator_id'].append('_'.join(
                    ['MV', str(grid.id_db), 'gen', str(node.id_db)]))
                generator['control'].append('PQ')
                generator['p_nom'].append(node.peak_generation)
                generator['grid_id'].append(grid.id_db)
                generator['bus'].append(node.pypsa_bus_id)

                generator_pq_set['generator_id'].append('_'.join(
                    ['MV', str(grid.id_db), 'gen', str(node.id_db)]))
                generator_pq_set['temp_id'].append(1)
                generator_pq_set['p_set'].append(
                    [node.peak_generation * kw2mw * generation_in_load_case,
                     node.peak_generation * kw2mw])
                generator_pq_set['q_set'].append(
                    [node.peak_generation * kw2mw * Q_factor_generation * generation_in_load_case,
                     node.peak_generation * kw2mw * Q_factor_generation])
                generator_pq_set['grid_id'].append(grid.id_db)

            elif isinstance(node, CircuitBreakerDing0):
                # TODO: remove this elif-case if CircuitBreaker are removed from graph
                continue
            else:
                raise TypeError("Node of type", node, "cannot be handled here")
        else:
            if not isinstance(node, CircuitBreakerDing0):
                add_info =  "LA is aggr. {0}".format(
                    node.lv_load_area.is_aggregated)
            else:
                add_info = ""
            logger.warning("Node {0} is not connected to the graph and will " \
                  "be omitted in power flow analysis. {1}".format(
                node, add_info))

    components = {'Bus': DataFrame(buses).set_index('bus_id'),
                  'Generator': DataFrame(generator).set_index('generator_id'),
                  'Load': DataFrame(load).set_index('load_id')}

    components_data = {'Bus': DataFrame(bus_v_mag_set).set_index('bus_id'),
                       'Generator': DataFrame(generator_pq_set).set_index(
                           'generator_id'),
                       'Load': DataFrame(load_pq_set).set_index('load_id')}

    # with open('/home/guido/ding0_debug/number_of_nodes_buses.csv', 'a') as csvfile:
    #     csvfile.write(','.join(['\n', str(len(nodes)), str(len(grid.graph_isolated_nodes())), str(len(components['Bus']))]))

    return components, components_data

def fill_component_dataframes(grid, buses_df, lines_df, transformer_df, generators_df, loads_df, only_export_mv = False):
    '''
    Parameters
    ----------
    grid: GridDing0
        Grid that is exported
    buses_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of buses with entries name,v_nom,geom,mv_grid_id,lv_grid_id,in_building
    lines_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of lines with entries name,bus0,bus1,length,x,r,s_nom,num_parallel,type
    transformer_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of trafos with entries name,bus0,bus1,x,r,s_nom,type
    generators_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of generators with entries name,bus,control,p_nom,type,weather_cell_id,subtype
    loads_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of loads with entries name,bus,peak_load,sector
    Returns
    -------
    :obj:`dict`
        Dictionary of component Dataframes 'Bus', 'Generator', 'Line', 'Load', 'Transformer'
    '''
    nodes = grid._graph.nodes()

    edges = [edge for edge in list(grid.graph_edges())
             if (edge['adj_nodes'][0] in nodes and not isinstance(
            edge['adj_nodes'][0], LVLoadAreaCentreDing0))
             and (edge['adj_nodes'][1] in nodes and not isinstance(
            edge['adj_nodes'][1], LVLoadAreaCentreDing0))]


    for trafo in grid.station()._transformers:
        transformer_df = append_transformers_df(transformer_df, trafo)

    node_components = nodes_to_dict_of_dataframes_for_csv_export(grid, nodes, buses_df, generators_df,
                                                                 loads_df, transformer_df, only_export_mv)
    branch_components = edges_to_dict_of_dataframes_for_csv_export(edges, lines_df)
    components = merge_two_dicts(branch_components, node_components)
    return components

def nodes_to_dict_of_dataframes_for_csv_export(grid, nodes, buses_df, generators_df, loads_df,transformer_df, only_export_mv = False):
    """
    Creates dictionary of dataframes containing grid

    Parameters
    ----------
    grid: ding0.Network
    nodes: :obj:`list` of ding0 grid components objects
        Nodes of the grid graph
    buses_df: :pandas:`pandas.DataFrame<dataframe>`
            Dataframe of buses with entries name,v_nom,geom,mv_grid_id,lv_grid_id,in_building
    generators_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of generators with entries name,bus,control,p_nom,type,weather_cell_id,subtype
    loads_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of loads with entries name,bus,peak_load,sector
    only_export_mv: bool
        Bool that indicates whether only mv grid should be exported, per default lv grids are exported too

    Returns:
    components: dict of :pandas:`pandas.DataFrame<dataframe>`
        DataFrames contain components attributes. Dict is keyed by components
        type
    """
    # TODO: MVStationDing0 has a slack generator, Do we want this?

    srid = int(cfg_ding0.get('geo', 'srid'))
    for isl_node in grid.graph_isolated_nodes():
        if isinstance(isl_node,LVStationDing0) and isl_node.lv_load_area.is_aggregated:
            continue
        elif isinstance(isl_node, CircuitBreakerDing0):
            continue
        else:
            print("{} is isolated node. Please check.".format(repr(isl_node))) #Todo: Umwandeln in Exception

    for node in nodes:
        if node not in grid.graph_isolated_nodes():
            # buses only
            if (isinstance(node, MVCableDistributorDing0) or isinstance(node, LVCableDistributorDing0)):
                buses_df = append_buses_df(buses_df, grid, node, srid)
      
            # slack generator
            elif isinstance(node, MVStationDing0):
                # add dummy generator
                slack = pd.Series({'name':('_'.join(['MV', str(grid.id_db), 'slack'])),
                                   'bus':node.pypsa_bus0_id, 'control':'Slack', 'p_nom':0, 'type': 'station',
                                   'subtype':'mv_station'})
                generators_df = generators_df.append(slack, ignore_index=True)
                # add HV side bus
                bus_HV = pd.Series({'name':node.pypsa_bus0_id, 'v_nom':110,
                                    'geom':from_shape(node.geo_data, srid=srid),'mv_grid_id': grid.id_db, 
                                    'in_building': False})
                buses_df = buses_df.append(bus_HV,ignore_index=True)
                # add MV side bus
                buses_df = append_buses_df(buses_df, grid, node, srid)

            # other generators
            elif isinstance(node, GeneratorDing0):
                generators_df = append_generators_df(generators_df, node)
                buses_df = append_buses_df(buses_df, grid, node, srid)
                
            elif isinstance(node, LoadDing0):
                for sector in node.consumption:
                    load = pd.Series({'name': repr(node), 'bus': node.pypsa_bus_id,
                                      'peak_load': node.peak_load, 'sector': sector})
                    loads_df = loads_df.append(load, ignore_index=True)
                buses_df = append_buses_df(buses_df,grid,node,srid)

            # aggregated load at hv/mv substation
            elif isinstance(node, LVLoadAreaCentreDing0):
                if (node.lv_load_area.peak_load!=0):
                    loads_df, generators_df = append_load_areas_to_df(loads_df, generators_df, node)



            # bus + aggregate load of lv grids (at mv/ls substation)
            elif isinstance(node, LVStationDing0):
                if isinstance(grid, ding0_nw.grids.MVGridDing0): #Todo: remove ding0_nw.grids when functions are thinned out
                    # Aggregated load representing load in LV grid, only needed when LV_grids are not exported
                    if only_export_mv:
                        loads_df, generators_df = append_load_areas_to_df(loads_df, generators_df, node)
                        for trafo in node.transformers():
                            transformer_df = append_transformers_df(transformer_df,trafo)
                        # bus at secondary MV-LV transformer side
                        buses_df = append_buses_df(buses_df, grid, node, srid, node.pypsa_bus0_id)
                    # bus at primary MV-LV transformer side
                    buses_df = append_buses_df(buses_df, grid, node, srid)
                elif isinstance(grid, ding0_nw.grids.LVGridDing0):
                    # bus at secondary MV-LV transformer side
                    buses_df = append_buses_df(buses_df, grid, node, srid,node.pypsa_bus0_id)
                else: 
                    raise TypeError('Something went wrong. Only LVGridDing0 or MVGridDing0 can be handled as grid.')
            elif isinstance(node, CircuitBreakerDing0):
                # TODO: remove this elif-case if CircuitBreaker are removed from graph
                continue
            else:
                raise TypeError("Node of type", node, "cannot be handled here")
        else:
            if not isinstance(node, CircuitBreakerDing0):
                add_info =  "LA is aggr. {0}".format(
                    node.lv_load_area.is_aggregated)
            else:
                add_info = ""
            logger.warning("Node {0} is not connected to the graph and will " \
                  "be omitted in power flow analysis. {1}".format(
                node, add_info))
            #Todo: Should these nodes not be exported?

    nodal_components = {'Bus': buses_df.set_index('name'),
                        'Generator': generators_df.set_index('name'),
                        'Load': loads_df.set_index('name'),
                        'Transformer': transformer_df.set_index('name')}

    return nodal_components


def append_load_areas_to_df(loads_df, generators_df, node):
    '''
    Appends lv load area to dataframe of nodes. Each sector (agricultural, industrial, residential, retail)
    is represented by own entry.

    Parameters
    ----------
    loads_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of loads with entries name,bus,peak_load,sector
    node: :obj: ding0 grid components object
        Node of lv load area or lv station

    Returns:
    loads_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of loads with entries name,bus,peak_load,sector
    '''





    if isinstance(node,LVStationDing0):
        name_bus = node.pypsa_bus_id
        grid_districts=[node.grid.grid_district]
        node_name = '_'.join(['Generator', 'mvgd' + str(node.grid.grid_district.lv_load_area.mv_grid_district.id_db), 'lcg' + str(node.id_db)])
        name_load = '_'.join(['Load','mvgd' + str(node.grid.grid_district.lv_load_area.mv_grid_district.id_db), 'lac' + str(node.id_db)])
    elif isinstance(node,LVLoadAreaCentreDing0):
        name_bus = node.grid.station().pypsa_bus_id
        grid_districts = node.lv_load_area._lv_grid_districts
        node_name = '_'.join(['Generator', 'mvgd' + str(node.grid.id_db), 'lcg' + str(node.id_db)])
        name_load = '_'.join(['Load','mvgd' + str(node.grid.id_db), 'lac' + str(node.id_db)])
    else:
        raise TypeError("Only LVStationDing0 or LVLoadAreaCentreDing0 can be inserted into function append_load_areas_to_df.")

    aggregated = determine_aggregated_nodes(node, grid_districts)
    generators_df = append_aggregated_generators_df(aggregated, generators_df, node, node_name)
    if (node.lv_load_area.peak_load_agricultural != 0):
        load = pd.Series({'name': '_'.join([name_load,'agr']), 'bus': name_bus,
                          'peak_load': node.lv_load_area.peak_load_agricultural, 'sector': "agricultural"})
        loads_df = loads_df.append(load, ignore_index=True)
    if (node.lv_load_area.peak_load_industrial != 0):
        load = pd.Series({'name': '_'.join([name_load,'ind']), 'bus': name_bus,
                          'peak_load': node.lv_load_area.peak_load_industrial,
                          'sector': "industrial"})
        loads_df = loads_df.append(load, ignore_index=True)
    if (node.lv_load_area.peak_load_residential != 0):
        load = pd.Series({'name': '_'.join([name_load,'res']), 'bus': name_bus,
                          'peak_load': node.lv_load_area.peak_load_residential,
                          'sector': "residential"})
        loads_df = loads_df.append(load, ignore_index=True)
    if (node.lv_load_area.peak_load_retail != 0):
        load = pd.Series({'name': '_'.join([name_load,'ret']), 'bus': name_bus,
                          'peak_load': node.lv_load_area.peak_load_retail,
                          'sector': "retail"})
        loads_df = loads_df.append(load, ignore_index=True)
    return loads_df, generators_df


def append_generators_df(generators_df, node):
    '''
    Appends generator to dataframe of generators in pypsa format.

    Parameters
    ----------
    generators_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of generators with entries name,bus,control,p_nom,type,weather_cell_id,subtype
    node: :obj: ding0 grid components object
        GeneratorDing0

    Returns:
    generators_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of generators with entries name,bus,control,p_nom,type,weather_cell_id,subtype
    '''
    if isinstance(node,GeneratorFluctuatingDing0):
        weather_cell_id = node.weather_cell_id
    else:
        weather_cell_id = np.NaN
    generator = pd.Series({'name':repr(node),
                           'bus': node.pypsa_bus_id, 'control':'PQ', 'p_nom':(node.capacity * node.capacity_factor),
                           'type':node.type, 'subtype':node.subtype, 'weather_cell_id':weather_cell_id})
    generators_df = generators_df.append(generator, ignore_index=True)
    return generators_df


def append_buses_df(buses_df, grid, node, srid, node_name =''):
    '''
    Appends buses to dataframe of buses in pypsa format.

    Parameters
    ----------
    buses_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of buses with entries name,v_nom,geom,mv_grid_id,lv_grid_id,in_building
    grid: ding0.Network
    node: :obj: ding0 grid components object
    srid: int
    node_name: str
        name of node, per default is set to node.pypsa_bus_id

    Returns:
    buses_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of buses with entries name,v_nom,geom,mv_grid_id,lv_grid_id,in_building
    '''
    # set default name of node
    if node_name == '':
        node_name = node.pypsa_bus_id
    # check if node is in building
    if isinstance(node, LVCableDistributorDing0):
        in_building = node.in_building
    else:
        in_building = False
    # set geodata, if existing
    geo = np.NaN
    if isinstance(node.geo_data,Point):
        geo = from_shape(node.geo_data, srid=srid)
    #set grid_ids
    if isinstance(grid, ding0_nw.grids.MVGridDing0):
        mv_grid_id = grid.id_db
        lv_grid_id = np.NaN
    elif isinstance(grid, ding0_nw.grids.LVGridDing0):
        mv_grid_id = grid.grid_district.lv_load_area.mv_grid_district.mv_grid.id_db
        lv_grid_id = grid.id_db
    else:
        raise TypeError('Something went wrong, only MVGridDing0 and LVGridDing0 should be inserted as grid.')
    # create bus dataframe
    bus = pd.Series({'name': node_name,'v_nom':grid.v_level, 'geom':geo,
                     'mv_grid_id':mv_grid_id,'lv_grid_id':lv_grid_id, 'in_building': in_building})
    buses_df = buses_df.append(bus, ignore_index=True)
    return buses_df

def append_transformers_df(transformers_df, trafo):
    '''
    Appends transformer to dataframe of buses in pypsa format.

    Parameters
    ----------
    transformers_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of trafos with entries name,bus0,bus1,x,r,s_nom,type
    trafo: :obj:TransformerDing0
        Transformer to be added
    name_trafo: str
        Name of transformer
    name_bus1: str
        name of secondary bus

    Returns:
    transformers_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of trafos with entries name,bus0,bus1,x,r,s_nom,type
    '''
    trafo_tmp = pd.Series({'name': repr(trafo), 'bus0':trafo.grid.station().pypsa_bus0_id,
                           'bus1':trafo.grid.station().pypsa_bus_id, 'x':trafo.x_pu, 'r':trafo.r_pu,
                           's_nom':trafo.s_max_a, 'type':' '.join([str(trafo.s_max_a), 'kVA'])})
    transformers_df = transformers_df.append(trafo_tmp,ignore_index=True)
    return transformers_df

def edges_to_dict_of_dataframes(grid, edges):
    """
    Export edges to DataFrame

    Parameters
    ----------
    grid: ding0.Network
    edges: :obj:`list`
        Edges of Ding0.Network graph

    Returns
    -------
    edges_dict: dict
    """
    freq = cfg_ding0.get('assumptions', 'frequency')
    omega = 2 * pi * freq
    srid = int(cfg_ding0.get('geo', 'srid'))

    lines = {'line_id': [], 'bus0': [], 'bus1': [], 'x': [], 'r': [],
             's_nom': [], 'length': [], 'cables': [], 'geom': [],
             'grid_id': []}

    # iterate over edges and add them one by one
    for edge in edges:

        line_name = repr(edge['branch'])

        # TODO: find the real cause for being L, C, I_th_max type of Series
        if (isinstance(edge['branch'].type['L_per_km'], Series) or#warum wird hier c abgefragt?
                isinstance(edge['branch'].type['C_per_km'], Series)):
            x_per_km = omega * edge['branch'].type['L_per_km'].values[0] * 1e-3
        else:

            x_per_km = omega * edge['branch'].type['L_per_km'] * 1e-3

        if isinstance(edge['branch'].type['R_per_km'], Series):
            r_per_km = edge['branch'].type['R_per_km'].values[0]
        else:
            r_per_km = edge['branch'].type['R_per_km']

        if (isinstance(edge['branch'].type['I_max_th'], Series) or
                isinstance(edge['branch'].type['U_n'], Series)):
            s_nom = sqrt(3) * edge['branch'].type['I_max_th'].values[0] * \
                    edge['branch'].type['U_n'].values[0]
        else:
            s_nom = sqrt(3) * edge['branch'].type['I_max_th'] * \
                    edge['branch'].type['U_n']

        # get lengths of line
        l = edge['branch'].length / 1e3

        lines['line_id'].append(line_name)
        lines['bus0'].append(edge['adj_nodes'][0].pypsa_bus_id)
        lines['bus1'].append(edge['adj_nodes'][1].pypsa_bus_id)
        lines['x'].append(x_per_km * l)
        lines['r'].append(r_per_km * l)
        lines['s_nom'].append(s_nom)
        lines['length'].append(l)
        lines['cables'].append(3)
        lines['geom'].append(from_shape(
            LineString([edge['adj_nodes'][0].geo_data,
                        edge['adj_nodes'][1].geo_data]),
            srid=srid))
        lines['grid_id'].append(grid.id_db)

    return {'Line': DataFrame(lines).set_index('line_id')}

def edges_to_dict_of_dataframes_for_csv_export(edges, lines_df):
    """
    Export edges to DataFrame

    Parameters
    ----------
    edges: :obj:`list`
        Edges of Ding0.Network graph
    lines_df: :pandas:`pandas.DataFrame<dataframe>`
            Dataframe of lines with entries name,bus0,bus1,length,x,r,s_nom,num_parallel,type
        

    Returns
    -------
    edges_dict: dict
    """

    # iterate over edges and add them one by one
    for edge in edges:
        if not edge['branch'].connects_aggregated:
            lines_df = append_lines_df(edge, lines_df)
        else:
            node = edge['adj_nodes']

        if isinstance(edge['adj_nodes'][0], LVLoadAreaCentreDing0) or isinstance(edge['adj_nodes'][1],LVLoadAreaCentreDing0):
            print()

    return {'Line': lines_df.set_index('name')}


def append_lines_df(edge, lines_df):
    freq = cfg_ding0.get('assumptions', 'frequency')
    omega = 2 * pi * freq
    # TODO: find the real cause for being L, C, I_th_max type of Series
    if (isinstance(edge['branch'].type['L_per_km'], Series)):
        x_per_km = omega * edge['branch'].type['L_per_km'].values[0] * 1e-3
    else:

        x_per_km = omega * edge['branch'].type['L_per_km'] * 1e-3
    if isinstance(edge['branch'].type['R_per_km'], Series):
        r_per_km = edge['branch'].type['R_per_km'].values[0]
    else:
        r_per_km = edge['branch'].type['R_per_km']
    if (isinstance(edge['branch'].type['I_max_th'], Series) or
            isinstance(edge['branch'].type['U_n'], Series)):
        s_nom = sqrt(3) * edge['branch'].type['I_max_th'].values[0] * \
                edge['branch'].type['U_n'].values[0]
    else:
        s_nom = sqrt(3) * edge['branch'].type['I_max_th'] * \
                edge['branch'].type['U_n']
    # get lengths of line
    length = edge['branch'].length / 1e3
    #Todo: change into same format
    if 'name' in edge['branch'].type:
        type = edge['branch'].type['name']
    else:
        type = edge['branch'].type.name

    line = pd.Series({'name':repr(edge['branch']),'bus0':edge['adj_nodes'][0].pypsa_bus_id, 'bus1':edge['adj_nodes'][1].pypsa_bus_id,
                      'x':x_per_km * length, 'r':r_per_km * length, 's_nom':s_nom, 'length':length, 
                      'num_parallel':1, 'type':type})
    lines_df = lines_df.append(line, ignore_index=True)
    return lines_df


def run_powerflow_onthefly(components, components_data, grid, export_pypsa_dir=None, debug=False):
    """
    Run powerflow to test grid stability

    Two cases are defined to be tested here:
     i) load case
     ii) feed-in case

    Parameters
    ----------
    components: dict of :pandas:`pandas.DataFrame<dataframe>`
    components_data: dict of :pandas:`pandas.DataFrame<dataframe>`
    export_pypsa_dir: :obj:`str`
        Sub-directory in output/debug/grid/ where csv Files of PyPSA network are exported to.
        Export is omitted if argument is empty.
    """

    scenario = cfg_ding0.get("powerflow", "test_grid_stability_scenario")
    start_hour = cfg_ding0.get("powerflow", "start_hour")
    end_hour = cfg_ding0.get("powerflow", "end_hour")

    # choose temp_id
    temp_id_set = 1
    timesteps = 2
    start_time = datetime(1970, 1, 1, 00, 00, 0)
    resolution = 'H'

    # inspect grid data for integrity
    if debug:
        data_integrity(components, components_data)

    # define investigated time range
    timerange = DatetimeIndex(freq=resolution,
                              periods=timesteps,
                              start=start_time)

    # TODO: Instead of hard coding PF config, values from class PFConfigDing0 can be used here.

    # create PyPSA powerflow problem
    network, snapshots = create_powerflow_problem(timerange, components)

    # import pq-sets
    for key in ['Load', 'Generator']:
        for attr in ['p_set', 'q_set']:
            # catch MV grid districts without generators
            if not components_data[key].empty:
                series = transform_timeseries4pypsa(components_data[key][
                                                        attr].to_frame(),
                                                    timerange,
                                                    column=attr)
                import_series_from_dataframe(network,
                                             series,
                                             key,
                                             attr)
    series = transform_timeseries4pypsa(components_data['Bus']
                                        ['v_mag_pu_set'].to_frame(),
                                        timerange,
                                        column='v_mag_pu_set')

    import_series_from_dataframe(network,
                                 series,
                                 'Bus',
                                 'v_mag_pu_set')

    # add coordinates to network nodes and make ready for map plotting
    # network = add_coordinates(network)

    # start powerflow calculations
    network.pf(snapshots)

    # # make a line loading plot
    # # TODO: make this optional
    # plot_line_loading(network, timestep=0,
    #                   filename='Line_loading_load_case.png')
    # plot_line_loading(network, timestep=1,
    #                   filename='Line_loading_feed-in_case.png')

    # process results
    bus_data, line_data = process_pf_results(network)

    # assign results data to graph
    assign_bus_results(grid, bus_data)
    assign_line_results(grid, line_data)

    # export network if directory is specified
    if export_pypsa_dir:
        export_to_dir(network, export_dir=export_pypsa_dir)


def data_integrity(components, components_data):
    """
    Check grid data for integrity

    Parameters
    ----------
    components: dict
        Grid components
    components_data: dict
        Grid component data (such as p,q and v set points)

    Returns
    -------
    """

    data_check = {}

    for comp in ['Bus', 'Load']:  # list(components_data.keys()):
        data_check[comp] = {}
        data_check[comp]['length_diff'] = len(components[comp]) - len(
            components_data[comp])

    # print short report to user and exit program if not integer
    for comp in list(data_check.keys()):
        if data_check[comp]['length_diff'] != 0:
            logger.exception("{comp} data is invalid. You supplied {no_comp} {comp} "
                  "objects and {no_data} datasets. Check you grid data "
                  "and try again".format(comp=comp,
                                         no_comp=len(components[comp]),
                                         no_data=len(components_data[comp])))
            sys.exit(1)

def process_pf_results(network):
    """

    Parameters
    ----------
    network: pypsa.Network

    Returns
    -------
    bus_data: :pandas:`pandas.DataFrame<dataframe>`
        Voltage level results at buses
    line_data: :pandas:`pandas.DataFrame<dataframe>`
        Resulting apparent power at lines
    """

    bus_data = {'bus_id': [], 'v_mag_pu': []}
    line_data = {'line_id': [], 'p0': [], 'p1': [], 'q0': [], 'q1': []}

    # create dictionary of bus results data
    for col in list(network.buses_t.v_mag_pu.columns):
        bus_data['bus_id'].append(col)
        bus_data['v_mag_pu'].append(network.buses_t.v_mag_pu[col].tolist())

    # create dictionary of line results data
    for col in list(network.lines_t.p0.columns):
        line_data['line_id'].append(col)
        line_data['p0'].append(network.lines_t.p0[col].tolist())
        line_data['p1'].append(network.lines_t.p1[col].tolist())
        line_data['q0'].append(network.lines_t.q0[col].tolist())
        line_data['q1'].append(network.lines_t.q1[col].tolist())

    return DataFrame(bus_data).set_index('bus_id'), \
           DataFrame(line_data).set_index('line_id')


def assign_bus_results(grid, bus_data):
    """
    Write results obtained from PF to graph

    Parameters
    ----------
    grid: ding0.network
    bus_data: :pandas:`pandas.DataFrame<dataframe>`
        DataFrame containing voltage levels obtained from PF analysis
    """

    # iterate of nodes and assign voltage obtained from power flow analysis
    for node in grid._graph.nodes():
        # check if node is connected to graph
        if (node not in grid.graph_isolated_nodes()
            and not isinstance(node,
                               LVLoadAreaCentreDing0)):
            if isinstance(node, LVStationDing0):
                node.voltage_res = bus_data.loc[node.pypsa_bus_id, 'v_mag_pu']
            elif isinstance(node, (LVStationDing0, LVLoadAreaCentreDing0)):
                if node.lv_load_area.is_aggregated:
                    node.voltage_res = bus_data.loc[node.pypsa_bus_id, 'v_mag_pu']
            elif not isinstance(node, CircuitBreakerDing0):
                node.voltage_res = bus_data.loc[node.pypsa_bus_id, 'v_mag_pu']
            else:
                logger.warning("Object {} has been skipped while importing "
                               "results!")


def assign_line_results(grid, line_data):
    """
    Write results obtained from PF to graph

    Parameters
    -----------
    grid: ding0.network
    line_data: :pandas:`pandas.DataFrame<dataframe>`
        DataFrame containing active/reactive at nodes obtained from PF analysis
    """

    package_path = ding0.__path__[0]

    edges = [edge for edge in grid.graph_edges()
             if (edge['adj_nodes'][0] in grid._graph.nodes() and not isinstance(
            edge['adj_nodes'][0], LVLoadAreaCentreDing0))
             and (
             edge['adj_nodes'][1] in grid._graph.nodes() and not isinstance(
                 edge['adj_nodes'][1], LVLoadAreaCentreDing0))]

    decimal_places = 6
    for edge in edges:
        s_res = [
            round(sqrt(
                max(abs(line_data.loc[repr(edge['branch']), 'p0'][0]),
                    abs(line_data.loc[repr(edge['branch']), 'p1'][0])) ** 2 +
                max(abs(line_data.loc[repr(edge['branch']), 'q0'][0]),
                    abs(line_data.loc[repr(edge['branch']), 'q1'][0])) ** 2),decimal_places),
            round(sqrt(
                max(abs(line_data.loc[repr(edge['branch']), 'p0'][1]),
                    abs(line_data.loc[repr(edge['branch']), 'p1'][1])) ** 2 +
                max(abs(line_data.loc[repr(edge['branch']), 'q0'][1]),
                    abs(line_data.loc[repr(edge['branch']), 'q1'][1])) ** 2),decimal_places)]

        edge['branch'].s_res = s_res


def init_pypsa_network(time_range_lim):
    """
    Instantiate PyPSA network
    Parameters
    ----------
    time_range_lim:
    Returns
    -------
    network: PyPSA network object
        Contains powerflow problem
    snapshots: iterable
        Contains snapshots to be analyzed by powerplow calculation
    """
    network = Network()
    network.set_snapshots(time_range_lim)
    snapshots = network.snapshots

    return network, snapshots


def transform_timeseries4pypsa(timeseries, timerange, column=None):
    """
    Transform pq-set timeseries to PyPSA compatible format
    Parameters
    ----------
    timeseries: Pandas DataFrame
        Containing timeseries
    Returns
    -------
    pypsa_timeseries: Pandas DataFrame
        Reformated pq-set timeseries
    """
    timeseries.index = [str(i) for i in timeseries.index]

    if column is None:
        pypsa_timeseries = timeseries.apply(
            Series).transpose().set_index(timerange)
    else:
        pypsa_timeseries = timeseries[column].apply(
            Series).transpose().set_index(timerange)

    return pypsa_timeseries


def create_powerflow_problem(timerange, components):
    """
    Create PyPSA network object and fill with data
    Parameters
    ----------
    timerange: Pandas DatetimeIndex
        Time range to be analyzed by PF
    components: dict
    Returns
    -------
    network: PyPSA powerflow problem object
    """

    # initialize powerflow problem
    network, snapshots = init_pypsa_network(timerange)

    # add components to network
    for component in components.keys():
        network.import_components_from_dataframe(components[component],
                                                 component)

    return network, snapshots

def determine_aggregated_nodes(node, grid_districts):
    """Determine generation within load areas

    Parameters
    ----------
    node: LVLoadAreaCentre or LVStation
        Load Area Centers are Ding0 implementations for representating areas of
        high population density with high demand compared to DG potential.

    Returns
    -------
    :obj:`list` of dict
        aggregated
        Dict of the structure

        .. code:

            {'type': {
                'subtype': {
                    'ids': <ids of aggregated generator>,
                    'capacity'}
                }
            }

    """

    def aggregate_generators(gen, aggr):
        """Aggregate generation capacity

        Parameters
        ----------
        gen: ding0.core.GeneratorDing0
            Ding0 Generator object
        aggr: dict
            Aggregated generation capacity. For structure see
            `_determine_aggregated_nodes()`.

        Returns
        -------

        """

        if gen.type not in aggr:
            aggr[gen.type] = {}
        if gen.subtype not in aggr[gen.type]:
            aggr[gen.type].update(
                     {gen.subtype: {'ids': [gen.id_db],
                                'capacity': gen.capacity}})
        else:
            aggr[gen.type][gen.subtype][
                'ids'].append(gen.id_db)
            aggr[gen.type][gen.subtype][
                'capacity'] += gen.capacity

        return aggr


    aggregated = {}

    # Determine aggregated generation in LV grid
    for lvgd in grid_districts:
        weather_cell_ids = {}
        for gen in lvgd.lv_grid.generators():
            aggregated = aggregate_generators(gen, aggregated)

            # Get the aggregated weather cell id of the area
            # b
            if isinstance(gen, GeneratorFluctuatingDing0):
                if gen.weather_cell_id not in weather_cell_ids.keys():
                    weather_cell_ids[gen.weather_cell_id] = 1
                else:
                    weather_cell_ids[gen.weather_cell_id] += 1


        # Get the weather cell id that occurs the most if there are any generators
        if not(list(lvgd.lv_grid.generators())):
            weather_cell_id = None
        else:
            if weather_cell_ids:
                weather_cell_id = list(weather_cell_ids.keys())[
                    list(weather_cell_ids.values()).index(
                        max(weather_cell_ids.values()))]
            else:
                weather_cell_id = None


        for type in aggregated:
            for subtype in aggregated[type]:
                # make sure to check if there are any generators before assigning
                # a weather cell id
                if not(list(lvgd.lv_grid.generators())):
                    pass
                else:
                    aggregated[type][subtype]['weather_cell_id'] = \
                        weather_cell_id

    return aggregated

def append_aggregated_generators_df(aggregated, generators_df, node, node_name):
    """Add Generators and Loads to MV station representing aggregated generation
    capacity and load

    Parameters
    ----------
    aggregated: dict
        Information about aggregated load and generation capacity. For
        information about the structure of the dict see ... .
    generators_df: :pandas:`pandas.DataFrame<dataframe>`
        Dataframe of grid generators
    node: object
        Station or LoadAreaCentre
    Returns
    -------
    generators_df: :pandas:`pandas.DataFrame<dataframe>`
        Altered datafram eof grid generators
    """


    for type, val in aggregated.items():
        # add aggregated generators
        for subtype, val2 in val.items():
            if type in ['solar', 'wind']:
                weather_cell_id = val2['weather_cell_id']
            else:
                weather_cell_id = np.NaN

            generator = pd.Series({'name': node_name,
                                   'bus': node.grid.station().pypsa_bus_id, 'control': 'PQ',
                                   'p_nom': val2['capacity'],
                                   'type': type, 'subtype': subtype,
                                   'weather_cell_id': weather_cell_id})
            generators_df = generators_df.append(generator, ignore_index=True)

    return generators_df