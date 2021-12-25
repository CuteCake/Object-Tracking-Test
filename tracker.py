#Test a multi-object tracker on the environment from environment.py
import random
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import math
import pygame
from enviroment import Point, PointsEnv
from motionModel import ConstantVelocityFilter, ConstantVelocityConstantTurningRateFilter

from itertools import permutations


class Track: #This is a class for a track, which is tracking a single object using some filter
    '''
    This is a Track class that can automatically do management itself

    It have a timer of how long it has not recived observations, and how long it has not recived observations
    Use a upper level class to get the .isDead and .isConfirmedTrack to update the list of tracks

    To delete a track, delete the reference of the track from the upper level class, 
    hope the garbage collector will do the job
    '''
    def __init__(self,observation = None, motion_model = 'constant_velocity', track_id=None,
     time_to_confirm = 0.5, #time to confirm a track
     time_to_kill = 0.5):  #time to kill a track if not recived observations
        assert observation is not None

        if motion_model == 'constant_velocity': #set initial state from observation
            self.filter = ConstantVelocityFilter(
                x = observation[0],
                y = observation[1],
                vx = 0,
                vy = 0)
        elif motion_model == 'constant_velocity_constant_turning_rate':
            raise NotImplementedError
        else:
            raise NotImplementedError
        
        self.track_id = track_id
        self.time_recived_observations = 0
        self.time_not_recived_observations = 0
        self.time_to_confirm = time_to_confirm
        self.isConfirmedTrack = False
        self.time_to_kill = time_to_kill
        self.isDead = False

        print('Track created with id:', self.track_id)
    
    def __del__(self):
        print('Track deleted with id:', self.track_id)
    
    def doPredictionStep(self, dt) -> np.array:
        return self.filter.prediction(dt) #return the state vector and covariance

    def doCorrectionStep(self, observation, obsCov=None) -> None:
        stateVector = self.filter.correction(observation, observationCovariance=obsCov)
        return stateVector

    def doMaintenance(self, dt = None, observation = None) -> None:
        assert dt is not None

        if observation is None:
            self.time_not_recived_observations += dt
            self.time_recived_observations = 0
        else:
            self.time_recived_observations += dt
            self.time_not_recived_observations = 0

        #Update the status of the track
        if self.time_recived_observations > self.time_to_confirm:
            self.isConfirmedTrack = True
        if self.time_not_recived_observations > self.time_to_kill:
            self.isDead = True

    def getState(self) -> np.array:
        return self.filter.stateVector

    def getStateCovariance(self) -> np.array:
        return self.filter.stateCovariance

    def update(self, observation, dt, obsCov=None, doDeadReckoning=False) -> None:#This is abandonded
        raise NotImplementedError 
        #Do the maintenance of the track
        #Update the timers of the track
        if observation is None:
            doDeadReckoning = True
            self.time_not_recived_observations += dt
            self.time_recived_observations = 0
        else:
            self.time_recived_observations += dt
            self.time_not_recived_observations = 0

        #Update the status of the track
        if self.time_recived_observations > self.time_to_confirm:
            self.isConfirmedTrack = True
        if self.time_not_recived_observations > self.time_to_kill:
            self.isDead = True

        #Do the update
        stateVector = self.filter.update(observation, dt, observationCovariance=obsCov, doDeadReckoning=doDeadReckoning)
        return stateVector

class BaseTracker: #Base class for tracker, should be inherited (and overwritten by real tracker)
    def __init__(self) -> None:
        pass
    def updateTracker(self, observation, dt) -> None:
        raise NotImplementedError
        return self.state_estimate  
        
class SingleTracker(BaseTracker): #This is a simple Extended Kalman Filter tracker
    '''
    This is a single object Kalman Filter tracker
    '''
    def __init__(self, sensor_noise = 5, measurement_noise = 5, 
        state_noise = 5, motion_model = 'constant_velocity'):
        self.sensor_noise = sensor_noise
        self.measurement_noise = measurement_noise
        self.state_noise = state_noise

        #The following are for logging purposes
        self.state_estimate = []
        self.state_estimate_history = []

        self.measurement_history = []
        self.prediction_history = []


        if motion_model == 'constant_velocity':
            self.motionFilter = ConstantVelocityFilter()
        elif motion_model == 'constant_turning_rate':
            self.motionFilter = ConstantVelocityConstantTurningRateFilter()
        else:
            raise Exception('Measurement model not supported')

    def updateTracker(self, observation, dt):
        print('dt: ', dt)
        self.state_estimate = self.motionFilter.update(observation, dt)

        return self.state_estimate

class MultiTracker(BaseTracker):
    '''
    A multi-object Kalman Filter tracker

    1. do data association (between detected objects with tracked objects)
        Method 1: GNN Global Nearest Neighbor
            It calculates the Mahalanobis distance (considers both position and covarience)
             between each detected object and tracked objects
            
        Method 2: JPDA Joint Probability Distance Association

    2. do the track management (delete, create tracks)
        Create: 
            1. When a new detection is there, create a new tentative track in the
            background and associate it with the detection
            2. When a tentative track is associated with a detection for a continuous
            of some times, put the track into the confirmed tracks

        Delete: When a track is not detected for a continuous of some time
                , delete the track
                When a track is too simillar to another track, delete the track
        
    3. update the Kalman Filter for each object
        Method 1: Use a single filter (KF,EKF,UKF, on some motion model)
        Method 2: Use a IMM Interactive Multi-Object Kalman Filter
              It updates one object using several models then outputs a weighted sum

    4. do gating (measurement validation)
        This is mainly for JPDA
        if the measurement is not in the gate range, don't waste the computation

    5. retun the state_estimate
    '''
    def __init__(self, obs = None, sensor_noise = 5, measurement_noise = 5, 
        state_noise = 5, motion_model = 'constant velocity',
        association_method = 'GNN'):
        self.sensor_noise = sensor_noise
        self.measurement_noise = measurement_noise
        self.state_noise = state_noise

        #The following are for logging purposes
        self.state_estimate = []
        self.state_estimate_history = []

        self.measurement_history = []
        self.prediction_history = []

        self.motion_model = motion_model
        self.association_method = association_method
        self.tracked_objects = [] #the list for tracks, including confirmed and tentative tracks
        self.next_track_id = 0

        #Initialize trackers
        assert obs is not None
        assert len(obs) > 1
        for i in range(len(obs)):
            self._createTrack(obs[i])

        
    def updateTracker(self, observation, dt, obsCov=None):
        
        '''
        observations -> [[x,y],[x,y],...]
        state_estimate -> [[x,y,vx,vy],[x,y,vx,vy],...]
        trackedObjects -> [TrackedObject,TrackedObject,...]
        '''
        #Call prediction step for every track's filter, get the new state_estimate for association
        #1. data association and track update
        if self.association_method == 'GNN':
            self._GNN_data_association(observation, dt, obsCov=obsCov)
        else:
            raise Exception('Association method not supported')
        #2. track management
        self._deleteDeadTracks()

        #3. gating
        return self.tracked_objects

    def _createTrack(self, observation):
        '''
        Create a new track for the observation
        '''
        self.next_track_id += 1
        self.tracked_objects.append(Track(observation = observation, \
            motion_model=self.motion_model, track_id=self.next_track_id))
        
        return self.next_track_id

    def _deleteDeadTracks(self):
        '''
        Delete a track
        '''
        for index, track in enumerate(self.tracked_objects):
            if track.isDead:
                self.tracked_objects.pop(index) #delete the track from the list, 
                #and the track will be deleted automatically
                #potential bug: the index of the list will be changed??
        return

    def _GNN_data_association(self, obs, obs_predicted, track_ids, obsCov=None):
        '''
        Data association using GNN

        we get every observation a track, 
        if an existing track is not found,
        we create a new track for it

        observation -> [[x,y],[x,y],...]

        return:
            association list -> [track_id, track_id,...]
             the length of the list is the number of observations

        '''
        #calculate euclidean distance, TODO use Mahalanobis distance
        min_sum_dist = np.inf
        permut = permutations(list(range(len(obs))),list(range(len(obs_predicted))))
        for combination in permut:
            sum_dist = 0
            #calculate the sum of euclidean distance
            for i in range(len(combination)):
                sum_dist += np.linalg.norm(obs[combination[i][0]]-obs_predicted[combination[i][1]])
            #check if the sum of distance is better
            if sum_dist < min_sum_dist:
                min_sum_dist = sum_dist
                best_comnination = combination
        return best_comnination[track_ids]

    def _JPDA_data_association(self, observation, dt, obsCov=None):
        raise NotImplementedError

    # def dataAssociation(self, observations, TrackedObjects):
    #     '''
    #     observations -> [[x,y],[x,y],...]
    #     state_estimate -> [[x,y,vx,vy],[x,y,vx,vy],...]
    #     trackedObjects -> [TrackedObject,TrackedObject,...]
    #     '''
    #     if self.association_method == 'GNN':
    #         #TODO
    #         return self.GNN(observations, state_estimate)
    #     else:
    #         raise Exception('Association method not supported')

    # def trackManagement(self, observations, TrackedObjects):
    #     pass

    # def updateTracker(self, observation, dt,):

    #     return self.state_estimate

    # def gating(self, observations, state_estimate):
    #     pass
    


if __name__ == "__main__":
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    env = PointsEnv(640, 480, 10)
    tracker = SingleTracker()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                print(env.get_time_elapsed())
                pygame.quit()
                quit()
        screen.fill((0, 0, 0))
        env.draw(screen)
        observation = env.update()
        
        env.draw_observed_points(screen, observation)
        obs = np.array(observation[0])
        stateVec = tracker.updateTracker(obs, env.get_last_dt())
        # env.draw_prediction(screen, stateVec)
        pygame.draw.circle(screen, (10,10, 255), (int(stateVec[0]),int(stateVec[1])), 5)
        pygame.display.update()
