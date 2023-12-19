from gym import Env
from gym import spaces
from gym.utils import seeding
from gym import spaces
import numpy as np
import math
from sumolib import checkBinary
import os, sys
import random
import traci
from scripts import utils
sys.path.append('../') #allows loading of agent.py
# from agent import Agent
import xml.etree.ElementTree as ET
import math
from itertools import combinations
import sumolib
class Agent:
    def __init__(self, env, n_agent, edge_agent=None):
        """Dummy agent object"""
        self.edge_agent = edge_agent
        self.traci = env.traci
        self.env = env

        self.id = n_agent
        self.name = f'agent {self.id}'

class SUMOEnv(Env):
	metadata = {'render.modes': ['human', 'rgb_array','state_pixels']}
	
	def __init__(self,reset_callback=None, reward_callback=None,
                 observation_callback=None, info_callback=None,
                 done_callback=None, shared_viewer=True,mode='gui',simulation_end=36000):
		self.pid = os.getpid()
		self.sumoCMD = []
		self._simulation_end = simulation_end
		self._mode = mode
		self._networkFileName = "sumo_configs/Grid1.net.xml"
		self._routeFileName = "sumo_configs/routes.rou.xml"
		# self._seed(40)
		np.random.seed(42)
		self.withGUI = mode
		self.action_steps = 25	
		self.traci = self.initSimulator(self.withGUI, self.pid)
		self._sumo_step = 0		
		self.shared_reward = True
		self._fatalErroFlag = False
		self._alreadyAddedFlag = False
		self._scenario = "Train"
		self._npc_vehicleID = 0
		self._rl_vehicleID = 0
		self._heuristic_vehicleID=0
		self._cav_vehicleID=0
		self.original_rl_vehicleID = []
		self._routeDict = {}
		self._timeLossOriginalDict = {}
		self._net = sumolib.net.readNet(self._networkFileName,withInternal=True)
		# set required vectorized gym env property
		self.n = 28
		self.lastActionDict = {}
		self.lastTimeLossRLAgents = {}
		self._lastOverAllTimeLoss = {}
		self._currentOverAllTimeLoss = {}
		self._lastOverAllWaitingTime = {}
		self._currentOverAllWaitingTime = {}
		self._listOfVehicleIdsInConcern = {}
		self._releventEdgeId = []
		self._timeLossThreshold = 60
		self._lane_clearing_distance_threshold = 30
		self._laneChangeAttemptDuration = 5 #seconds

		#test stats
		self._currentTimeLoss_rl = 0
		self._currentTimeLoss_npc = 0
		self._avg_speed_rl = 0
		self._avg_speed_npc = 0		
		self._average_edge_occupancy = 0
		self._average_PMx_emission = 0

		self._allEdgeIds = self.traci.edge.getIDList()
		for edge in self._allEdgeIds:
			if edge.find(":") == -1:
				self._releventEdgeId.append(edge)

		
		#############------------------------------------------------------------------#######################

		# for every trip there is a hypothetical duration tMIN that could be achieved if the vehicle was driving with its maximum
		# allowed speed (including speedFactor) and there were no other vehicles nor traffic rules.
		# timeLoss = tripDuration - tMIN
		# also, waiting time is always included in timeLoss, therefore
		# timeLoss >= waitingTime

		#############------------------------------------------------------------------#######################



		# priority_actions = ['0','1','2']
		# configure spaces
		# self._num_observation = [len(self.getState(f'RL_{i}')) for i in range(self.n)]
		# self._num_observation = [6,6]
		self._num_observation = 5
		self._num_actions = 3
		# self._num_actions = [len(priority_actions), len(priority_actions)]
		# self._num_observation = [len(Agent(self, i, self.edge_agents[0]).getState()) for i in range(self._num_lane_agents)]*len(self.edge_agents)
		self.action_space = []
		self.observation_space = []
		for i in range(self.n):
			self.action_space.append(spaces.Discrete(self._num_actions)) #action space			
			self.observation_space.append(spaces.Box(low=0, high=1, shape=(self._num_observation,)))# observation space
			
		self.agents = self.createNAgents()

		# parse the net

	def createNAgents(self):
		agents = [Agent(self, i) for i in range(self.n)]

		return agents
	
	def getState(self,agent_id):
		"""
		Retrieve the state of the network from sumo. 
		"""
		state = []
		# State = { Number of vehicle with priority lane access, number of vehicle without priority lane access, It’s own priority lane access, Avg. delay over all edges, number of emergency vehicle, number of public buses)
		#Get the edgeID on which the RL agent is:
		# agent_id = "RL_0"
		# print(agent_id)
		#Get the edgeID on which the RL agent is:
		edge_id = self.traci.vehicle.getRoadID(agent_id)
		# print(edge_id,agent_id)
		nextNodeID = self._net.getEdge(edge_id).getToNode().getID() # gives the intersection/junction ID
		# now found the edges that is incoming to this junction
		incomingEdgeList = self._net.getNode(nextNodeID).getIncoming()

	
		# # print(edge_id)
		# #Get the intersection the RL agent is going towards:
		# # retrieve the successor edges of an edge
		# nextEdges = self._net.getEdge(edge_id).getOutgoing()
		# edge_list = [e.getID() for e in nextEdges] # list of all edges excluding internal
		# nextIncomingEdges = self._net.getEdge(edge_id).getIncoming()
		# edge_list_incoming = [e.getID() for e in nextIncomingEdges] # list of all edges excluding internal
		priorityVehicleCount = 0
		nonPriorityVehicleCount = 0
		# total_waiting_time = 0
		accumulated_time_loss = 0
		normalization_totalNumberOfVehicle = 50
		elapsed_simulation_time = self.traci.simulation.getTime()
		edge_list_incoming = [e.getID() for e in incomingEdgeList] # list of all edges excluding internal
		for e_id in edge_list_incoming:   
			all_vehicle = self.traci.edge.getLastStepVehicleIDs(e_id)
			for veh in all_vehicle:
				elapsed_vehicle_time = self.traci.vehicle.getDeparture(veh)			
				accumulated_time_loss+=self.traci.vehicle.getTimeLoss(veh) / (elapsed_simulation_time - elapsed_vehicle_time)
				# total_waiting_time+=self.traci.vehicle.getAccumulatedWaitingTime(veh)
				priority_type = self.traci.vehicle.getTypeID(veh)
				if priority_type=="passenger-priority" or priority_type=="rl-priority":
					priorityVehicleCount+=1
				else:
					nonPriorityVehicleCount+=1
			
			
		elapsed_its_own_time = self.traci.vehicle.getDeparture(agent_id)	
		itsOwnTImeLoss = self.traci.vehicle.getTimeLoss(agent_id) / (elapsed_simulation_time - elapsed_its_own_time)
		# self.lastTimeLoss[agent_id] = itsOwnTImeLoss
		if self.traci.vehicle.getTypeID(agent_id)=="rl-priority":
			itsPriorityAccess = 1
		else:
			itsPriorityAccess = 0
		# print(self._sumo_step)
		state = [itsOwnTImeLoss/self.action_steps,itsPriorityAccess,priorityVehicleCount/normalization_totalNumberOfVehicle,nonPriorityVehicleCount/normalization_totalNumberOfVehicle,accumulated_time_loss/self.action_steps]
		# if agent_id == "RL_1":
		# 	print(state)
		return np.array(state)
	
	def keepRLAgentLooping(self):
		allVehicleList = self.traci.vehicle.getIDList()
		self._npc_vehicleID,self._rl_vehicleID,self._heuristic_vehicleID,self._cav_vehicleID = utils.getSplitVehiclesList(allVehicleList)
		missingRLAgentFlag = False
		# print(rl_vehicleID)
		if len(self._rl_vehicleID) != 28: #this it solve: sometimes self.traci/sumo drops vehicle due to some reason. To maintain the same number of RL agent 
			# print("number of RL vehicle -",len(self._rl_vehicleID))
			missingRLAgentFlag = True #find missing vehicle ID	
			missingRLList = set(self.original_rl_vehicleID).difference(self._rl_vehicleID)
			print("RL agent missing : ",missingRLList)
		# for rl_veh in self._rl_vehicleID:
		# 	print("Inside 0")
		# 	if self.traci.vehicle.getRouteIndex(str(rl_veh)) == (len(self.traci.vehicle.getRoute(str(rl_veh))) - 1): #Check to see if the car is at the end of its route
		# 		new_destiny = random.choice(self._releventEdgeId)
		# 		# print(str(rl_veh)+str(new_destiny))
		# 		self.traci.vehicle.changeTarget(str(rl_veh),str(new_destiny)) #Assign random destination
		if missingRLAgentFlag:
			# print(self.original_rl_vehicleID)
			# print(self._rl_vehicleID)
			for missRL in missingRLList:
				if missRL not in self.traci.simulation.getArrivedIDList():
					# print(self.traci.vehicle.getIDList())
					# try:
					# 	self.traci.vehicle.remove(missRL) # just in case
					# except:
					# 	pass # do nothing					
					edges = self._routeDict[missRL]
					# print(edges)
					if missRL not in self.traci.simulation.getArrivedIDList():
						#create the route
						# print(self.traci.route.getIDList())
						try:
							self.traci.route.add(missRL,edges)					
						except:
							pass
					# print(self.traci.route.getEdges(missRL))
					
					# try:					
					self.traci.simulationStep() 
					self.traci.vehicle.add(missRL,missRL,typeID="rl-priority")
					# except:
					# 	pass #do nothing
	
	def resetAllVariables(self):
		self.lastActionDict.clear()
		self._timeLossOriginalDict.clear()
		self._currentTimeLoss_rl = 0
		self._currentTimeLoss_npc = 0
		self._avg_speed_rl = 0
		self._avg_speed_npc = 0
		self._average_edge_occupancy = 0
		self._average_PMx_emission = 0

		# self._npc_vehicleID=0
		# self._rl_vehicleID=0

	def initializeRLAgentStartValues(self):
		for rl_agent in self.original_rl_vehicleID:
			self._timeLossOriginalDict[rl_agent] = self.traci.vehicle.getTimeLoss(rl_agent) # store the time loss when the agent is spawned. It will be used to compare for action step time loss for reward calculation
			# self._travelTime[rl_agent] = 
	
	def setHeuristicAgentTogglePriority(self): #heuristic logic to change priority of all agent starting with heuristic in the name. 
		#this is done to overcome the limitation of training 100's of RL agent. Can we just train 25% of the RL agent with heuristic logic and 
		#still get similar or better training output? One novelty of the paper, probably?
		allVehicleList = self.traci.vehicle.getIDList()
		print("Total number of vehicles",len(allVehicleList))
		self._npc_vehicleID,self._rl_vehicleID, self._heuristic_vehicleID,self._cav_vehicleID= utils.getSplitVehiclesList(allVehicleList)
		# for npc in self._npc_vehicleID:
		# 	assignPriority = random.uniform(0, 1)
		# 	if self.traci.vehicle.getTypeID(npc)=="passenger-priority": 
		# 		if assignPriority > 0.5:
		# 			self.traci.vehicle.setType(npc,"passenger-default")
		# 	elif self.traci.vehicle.getTypeID(npc)=="passenger-default": 
		# 		if assignPriority > 0.5:
		# 			self.traci.vehicle.setType(npc,"passenger-priority")
		for heuristic in self._heuristic_vehicleID:
			which_lane = self.traci.vehicle.getLaneID(heuristic)
			if self.edgeIdInternal(which_lane)==False:
				lane_index = which_lane.split("_")[1]
				which_edge = which_lane.split("_")[0]
				priority_lane = which_edge + str("_2") # find priority lane for that vehicle
				vehicle_on_priority_lane = self.traci.lane.getLastStepVehicleIDs(priority_lane)
				npc_vehicleID,rl_vehicleID, heuristic_vehicleID,cav_vehicleID= utils.getSplitVehiclesList(vehicle_on_priority_lane)
				heuristic_lane_position = self.traci.vehicle.getLanePosition(heuristic)

				for cav in cav_vehicleID:
					cav_lane_position = self.traci.vehicle.getLanePosition(cav)
					if heuristic_lane_position - cav_lane_position>= self._lane_clearing_distance_threshold:					
						continue
					else:
						#change priority of heuristic agent as it is inside clearing distance
						self.traci.vehicle.setType(heuristic,"heuristic-default")
						bestLanes = self.traci.vehicle.getBestLanes(heuristic)
						if bestLanes[0][1] > bestLanes[1][1]: # it checks the length that can be driven without lane
							#change for the prospective lanes (measured from the start of that lane). Higher value is preferred. 
							self.traci.vehicle.changeLane(heuristic,0,self._laneChangeAttemptDuration) 
						else:
							self.traci.vehicle.changeLane(heuristic,1, self._laneChangeAttemptDuration)
						break
				if lane_index!='2':
					self.traci.vehicle.setType(heuristic,"heuristic-priority")






			# assignPriority = random.uniform(0, 1)
			# if self.traci.vehicle.getTypeID(heuristic)=="heuristic-priority": 
			# 	if assignPriority > 0.5:
			# 		self.traci.vehicle.setType(heuristic,"heuristic-default")
			# elif self.traci.vehicle.getTypeID(heuristic)=="heuristic-default": https://sumo.dlr.de/pydoc/traci._lane.html#LaneDomain-getLastStepVehicleIDs
			# 	if assignPriority > 0.5:
			# 		self.traci.vehicle.setType(heuristic,"heuristic-priority")

	def reset(self,scenario):		
		print("--------Inside RESET---------")
		self._sumo_step = 0
		self._scenario = scenario
		self.resetAllVariables()
		obs_n = []
		self.traci.load(self.sumoCMD + ['-n', self._networkFileName, '-r', self._routeFileName])
		#WARMUP PERIOD
		while self._sumo_step <= self.action_steps:
			self.traci.simulationStep() 		# Take a simulation step to initialize	
			# print(self.traci.vehicle.getTimeLoss("RL_9"))
			if self._sumo_step == 10:
				allVehicleList = self.traci.vehicle.getIDList()
				self._npc_vehicleID,self.original_rl_vehicleID,self._heuristic_vehicleID,self._cav_vehicleID= utils.getSplitVehiclesList(allVehicleList)
				
				# self.initializeRLAgentStartValues()
			# 	self.keepRLAgentLooping()				
			self._sumo_step +=1

		#record observatinos for each agent
		
		# self.initializeNPCRandomPriority()
		for agent in self.agents:
			agent.done = False
			obs_n.append(self._get_obs(agent))
		#keep list of all route ID
		if self._alreadyAddedFlag == False:
			for rl_veh in self.original_rl_vehicleID:
				self.traci.route.add(rl_veh,self.traci.vehicle.getRoute(rl_veh))
				self._routeDict[rl_veh] = self.traci.vehicle.getRoute(rl_veh)
				self._alreadyAddedFlag = True
		# 		# print(rl_veh,self.traci.vehicle.getRoute(rl_veh))
		print("--------Outside RESET---------" + str(self._sumo_step))
		return obs_n

	# get observation for a particular agent
	def _get_obs(self, agent):
		return self.getState(f'RL_{agent.id}')
		# state = [0.1,0.3,0.5,0.6,0.8]
		# return state

	def computeCooperativeReward(self,rl_agent):
		elapsed_simulation_time = self.traci.simulation.getTime()
		elapsed_its_own_time = self.traci.vehicle.getDeparture(rl_agent)
		currentTimeLoss = self.traci.vehicle.getTimeLoss(rl_agent) / (elapsed_simulation_time - elapsed_its_own_time)
		diffTimeLoss = self.lastTimeLossRLAgents[rl_agent] - currentTimeLoss
		
		# if diffTimeLoss > 0 : It means good for positive reward
		diffTimeLossInSeconds = diffTimeLoss*(elapsed_simulation_time - elapsed_its_own_time)
		# if agent_id == "RL_0":
		# 	print(diffTimeLossInSeconds)
		# 	print(self.lastTimeLossRLAgents[agent_id]*(elapsed_simulation_time - elapsed_its_own_time))
		# 	print(currentTimeLoss*(elapsed_simulation_time - elapsed_its_own_time))

		if self.traci.vehicle.getTypeID(rl_agent)=="rl-priority": #check if agent 
			if self.lastActionDict[rl_agent] == 0: # give up the priority
				reward = +1*(diffTimeLoss)
				# if diffTimeLoss > 0:	
				# 	reward = +1*(diffTimeLoss)
				# else:
				# 	reward = +1*(diffTimeLoss)
				
			elif self.lastActionDict[rl_agent] == 1: # do nothing. Keep the same action
				reward = +1*(diffTimeLoss)
				# if diffTimeLoss > 0:				
				# 	reward = -1*(diffTimeLoss) #penalize because it is not cooperative even if it can
				# else:
				# 	reward = +1*(diffTimeLoss) #reward because it is trying to maximize it's own gain
			else: # ask for priority if priority				
				if diffTimeLoss > 0:
					reward = -0.1
				else:
					reward = 0

		if self.traci.vehicle.getTypeID(rl_agent)=="rl-default": #check if agent 
			if self.lastActionDict[rl_agent] == 0: # give up the priority
				if diffTimeLoss > 0:
					reward = 0
				else:
					reward = -0.1
			elif self.lastActionDict[rl_agent] == 1: # do nothing. Keep the same action
				reward = +1*(diffTimeLoss)
			else: # ask for priority if no priority
				reward = -1*(diffTimeLoss)

		return reward
	
	def computeOverallNetworkReward(self,rl_agent):		
		# delta_time_loss = self._currentOverAllTimeLoss[rl_agent] - self._lastOverAllTimeLoss[rl_agent]
		delta_waiting_time_loss = self._currentOverAllWaitingTime[rl_agent] - self._lastOverAllWaitingTime[rl_agent]
		# print(delta_time_loss,"--", self._currentOverAllWaitingTime[rl_agent], "--", self._lastOverAllWaitingTime[rl_agent])
		if delta_waiting_time_loss > 0:
			reward_timeLoss = -1
		else:
			reward_timeLoss = +1
		
		return reward_timeLoss

	# get reward for a particular agent
	def _get_reward(self,agent):
		agent_id = f'RL_{agent.id}'
		overall_reward = 0
		if len(self.lastActionDict) !=0:				
			reward_cooperative = self.computeCooperativeReward(agent_id)
			reward_overallNetwork = self.computeOverallNetworkReward(agent_id)
			overall_reward = reward_cooperative + reward_overallNetwork
			# print(overall_reward)		
			# overall_reward = 0	

		return overall_reward
		
	def _seed(self, seed=None):
		self.np_random, seed = seeding.np_random(seed)
		return [seed]

	def _get_done(self, agent):  
		return agent.done

	# get info used for benchmarking
	def _get_info(self, agent):
		return {}
	def edgeIdInternal(self,edge_id):
		if edge_id.find(":") == -1:
			return False
		else:
			return True
	
	def collectObservation(self,lastTimeStepFlag):
		#This function collects sum of time loss for all vehicles related to a in-concern RL agent. 
		allVehicleList = self.traci.vehicle.getIDList()
		self._npc_vehicleID,self._rl_vehicleID,self._heuristic_vehicleID,self._cav_vehicleID= utils.getSplitVehiclesList(allVehicleList)
		elapsed_simulation_time = self.traci.simulation.getTime()
		if lastTimeStepFlag:			
			for rl_agent in self._rl_vehicleID:
				elapsed_its_own_time = self.traci.vehicle.getDeparture(rl_agent)
				itsOwnTImeLoss = self.traci.vehicle.getTimeLoss(rl_agent) / (elapsed_simulation_time - elapsed_its_own_time)
				self.lastTimeLossRLAgents[rl_agent] = itsOwnTImeLoss
				edge_id = self.traci.vehicle.getRoadID(rl_agent)
				accumulated_time_loss = 0
				total_waiting_time=0
				# print(edge_id,agent_id)
				#check if edge_id is internal
				# if self.edgeIdInternal(edge_id):
				# 	print("Internal Edge ID - ",edge_id) #change it to the main edge_id

				nextNodeID = self._net.getEdge(edge_id).getToNode().getID() # gives the intersection/junction ID
				# now found the edges that is incoming to this junction
				incomingEdgeList = self._net.getNode(nextNodeID).getIncoming()
				edge_list_incoming = [e.getID() for e in incomingEdgeList] # list of all edges excluding internal
				for e_id in edge_list_incoming:   
					all_vehicle = self.traci.edge.getLastStepVehicleIDs(e_id)
					self._listOfVehicleIdsInConcern[rl_agent] = all_vehicle
					for veh in all_vehicle:
						elapsed_vehicle_time = self.traci.vehicle.getDeparture(veh)
						accumulated_time_loss+=self.traci.vehicle.getTimeLoss(veh)/(elapsed_simulation_time - elapsed_vehicle_time)
						total_waiting_time+=self.traci.vehicle.getAccumulatedWaitingTime(veh)


				self._lastOverAllTimeLoss[rl_agent] = accumulated_time_loss
				self._lastOverAllWaitingTime[rl_agent] = total_waiting_time
		else:
			for rl_agent in self._rl_vehicleID:
				accumulated_time_loss = 0
				total_waiting_time=0
				for veh in self._listOfVehicleIdsInConcern[rl_agent]:
					elapsed_vehicle_time = self.traci.vehicle.getDeparture(veh)
					accumulated_time_loss+=self.traci.vehicle.getTimeLoss(veh)/(elapsed_simulation_time - elapsed_vehicle_time)
					total_waiting_time+=self.traci.vehicle.getAccumulatedWaitingTime(veh)

				self._currentOverAllWaitingTime[rl_agent] = total_waiting_time

	def collectObservationPerStep(self):
		elapsed_simulation_time = self.traci.simulation.getTime()
		allVehicleList = self.traci.vehicle.getIDList()
		self._npc_vehicleID,self._rl_vehicleID,self._heuristic_vehicleID,self._cav_vehicleID = utils.getSplitVehiclesList(allVehicleList)

		for rl_agent in self._rl_vehicleID:
			self._avg_speed_rl+=self.traci.vehicle.getSpeed(rl_agent)
			elapsed_its_own_time = self.traci.vehicle.getDeparture(rl_agent)
			self._currentTimeLoss_rl += self.traci.vehicle.getTimeLoss(rl_agent) / (elapsed_simulation_time - elapsed_its_own_time)
		self._currentTimeLoss_rl = self._currentTimeLoss_rl/len(self._rl_vehicleID)
		self._avg_speed_rl = self._avg_speed_rl/len(self._rl_vehicleID)
		for npc_agent in self._npc_vehicleID:
			self._avg_speed_npc+=self.traci.vehicle.getSpeed(npc_agent)
			elapsed_its_own_time = self.traci.vehicle.getDeparture(npc_agent)
			self._currentTimeLoss_npc += self.traci.vehicle.getTimeLoss(npc_agent) / (elapsed_simulation_time - elapsed_its_own_time)
		self._currentTimeLoss_npc = self._currentTimeLoss_npc/len(self._npc_vehicleID)
		self._avg_speed_npc = self._avg_speed_npc/len(self._npc_vehicleID)

		for edge in self._releventEdgeId:
			self._average_edge_occupancy += self.traci.edge.getLastStepOccupancy(edge)
			self._average_PMx_emission += self.traci.edge.getPMxEmission(edge)

		self._average_edge_occupancy = self._average_edge_occupancy/len(self._releventEdgeId)
		self._average_PMx_emission = self._average_PMx_emission/len(self._releventEdgeId)


	def getTestStats(self):
	
			avg_delay_RL=0;avg_speed_RL=0;avg_delay_NPC=0;avg_speed_NPC=0;avg_occupancy_network=0;avg_PMx_emisison=0

				
			avg_delay_RL = self._currentTimeLoss_rl/self.action_steps
			avg_speed_RL = self._avg_speed_rl/self.action_steps

			avg_delay_NPC = self._currentTimeLoss_npc/self.action_steps
			avg_speed_NPC = self._avg_speed_npc/self.action_steps

			avg_occupancy_network = self._average_edge_occupancy/self.action_steps
			avg_PMx_emisison = self._average_PMx_emission/self.action_steps

			
			headers = ['avg_delay_RL', 'avg_speed_RL','avg_delay_NPC', 'avg_speed_NPC','congestion(avg_occupancy_network))','avg_PMx_emission']
			values = [avg_delay_RL, avg_speed_RL, avg_delay_NPC,avg_speed_NPC,avg_occupancy_network,avg_PMx_emisison]
			return headers, values
	
	def make_action(self,actions):
		agent_actions = []
		for i in range(0,self.n): 
			index = np.argmax(actions[i])
			agent_actions.append(index)
		return agent_actions
	
	def _step(self,action_n):

		print("--------Inside STEP-----------")
		obs_n = []
		reward_n = []
		done_n = []
		info_n = {'n':[]}
		actionFlag = True
		for agent in self.agents:
			agent.done = False

		
		self._sumo_step = 0
		
		if actionFlag == True:
			temp_action_dict = {}
			simple_actions = self.make_action(action_n)
			# print(simple_actions)
			for i, agent in enumerate(self.agents):
				self.lastActionDict[f'RL_{agent.id}'] = simple_actions[i]
			
			self.collectObservation(True)		#Observation before taking an action - lastTimeStepFlag
			self._set_action()			
			
			actionFlag = False
		
		
		self.traci.simulation.saveState('sumo_configs/savedstate.xml')
		# self.initializeRLAgentStartValues()
		vehicleCount = 0
		while self._sumo_step <= self.action_steps:
			# advance world state
			self.collectObservationPerStep()
			self.traci.simulationStep()
			self._sumo_step +=1	
			# self.collectObservation(False) ##Observation at each step till the end of the action step count (for reward computation) - lastTimeStepFlag lastTimeStepFlag
			# self.keepRLAgentLooping()
			# for loop in self.traci.inductionloop.getIDList():
			# 	vehicleCount +=self.traci.inductionloop.getLastStepVehicleNumber(loop)
			
		# print("Average Number of Vehicles per edge in five minutes are :",vehicleCount/len(self.traci.inductionloop.getIDList()))
		# print(len(self.traci.inductionloop.getIDList()))

		self.collectObservation(False) #lastTimeStepFlag
		allVehicleList = self.traci.vehicle.getIDList()
		self._npc_vehicleID,self._rl_vehicleID,self._heuristic_vehicleID,self._cav_vehicleID = utils.getSplitVehiclesList(allVehicleList)
		# print("Total npc: " + str(len(self._npc_vehicleID)) + "Total RL agent: " + str(len(self._rl_vehicleID)))

		if len(self._rl_vehicleID)!=28:
			print("Total RL agent before loadState: " + str(len(self._rl_vehicleID)))
			self.traci.simulation.loadState('sumo_configs/savedstate.xml')
			print("Total RL agent After loadState: " + str(len(self._rl_vehicleID)))
			# self.keepRLAgentLooping()


			
		# allVehicleList = self.traci.vehicle.getIDList()
		# self._npc_vehicleID,self._rl_vehicleID = utils.getSplitVehiclesList(allVehicleList)
		# print("Total npc: " + str(len(self._npc_vehicleID)) + "Total RL agent: " + str(len(self._rl_vehicleID)))
		
		

		for agent in self.agents:
			obs_n.append(self._get_obs(agent))	
			# print(self._get_obs(agent))		
			reward_n.append(self._get_reward(agent))
			# print(self._get_reward(agent))
			done_n.append(self._get_done(agent))

			info_n['n'].append(self._get_info(agent))

		self._currentReward = reward_n
		reward = np.sum(reward_n)
		if self.shared_reward:
			reward_n = [reward] *self.n
		# print("Reward = " + str(reward_n))
		self._lastReward = reward_n[0]
		# print("reward: " + str(self._lastReward))

		return obs_n, reward_n, done_n, info_n

	# set env action for a particular agent
	def _set_action(self,time=None):
		# process action
		#index 0 = # give up the priority
		#index 1 = # do nothing
		#index 2 = # ask for priority
		self.setHeuristicAgentTogglePriority() # to simulate human decision-making
		for agent in self.agents: #loop through all agent
			agent_id = f'RL_{agent.id}'
			action = self.lastActionDict[agent_id]
			# action = 1
			# if action==2:
			# 	print(action)
			if self.traci.vehicle.getTypeID(agent_id)=="rl-priority": #check if agent  
				if action == 0:
					self.traci.vehicle.setType(agent_id,"rl-default")
					# print("Priority Removed")
				elif action == 1:
					pass # do nothing
				else:
					pass # if action = 2. Still do nothing. It already has priority
			else:
				if action == 0:
					pass # do nothing. It has no priority to give
				elif action == 1:
					pass # do nothing
				else:
					self.traci.vehicle.setType(agent_id,"rl-priority")
					# print("Priority Assigned")
	
	def initSimulator(self,withGUI,portnum):
		if withGUI:
			import traci
		else:
			try:
				import libsumo as traci
			except:
				import traci
		seed = 42
		self._networkFileName = "sumo_configs/Grid1.net.xml"
		self.sumoCMD = ["--seed", str(seed),"--waiting-time-memory",str(self.action_steps),"--time-to-teleport", str(-1),
				 "--no-step-log","--lanechange.duration",str(3),"--statistic-output","output.xml"]
   
  
		if withGUI:
			sumoBinary = checkBinary('sumo-gui')
			# sumoCMD += ["--start", "--quit-on-end"]
			self.sumoCMD += ["--start"]
			# self.sumoCMD += ["--start", "--quit-on-end"]
		else:	
			sumoBinary = checkBinary('sumo')

		# print(sumoBinary)
		sumoConfig = "sumo_configs/sim.sumocfg"
		self.sumoCMD = ["-c", sumoConfig] + self.sumoCMD


		random.seed(seed)
		traci.start([sumoBinary] + self.sumoCMD)
		return traci

	def closeSimulator(traci):
		traci.close()
		sys.stdout.flush()

