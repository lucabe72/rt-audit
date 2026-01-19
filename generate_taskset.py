#!/usr/bin/env python3
"""
RT-Audit: Real-Time Taskset Auditor
Workload Generator for SCHED_DEADLINE Testing

This script generates synthetic real-time workloads using the UUniFast algorithm
to create realistic SCHED_DEADLINE tasksets for rt-app testing.
"""

import json
import random
import argparse
import math
import time
import sys
import os

def uunifast(n, u_total):
    """
    The UUniFast algorithm for generating task utilizations.
    This algorithm generates a set of 'n' utilizations that sum to 'u_total'.

    Args:
        n (int): The number of tasks.
        u_total (float): The total utilization to be distributed.

    Returns:
        list: A list of 'n' floating-point utilization values.
    """
    utilizations = []
    sum_u = u_total
    for i in range(1, n):
        # Generate a random value and scale it to the remaining utilization
        next_sum_u = sum_u * random.random() ** (1.0 / (n - i))
        utilizations.append(sum_u - next_sum_u)
        sum_u = next_sum_u
    utilizations.append(sum_u)
    return utilizations

def generate_taskset(num_tasks, period_min_ms, period_max_ms, period_gran_ms, max_task_util, total_utilization, verbose=False):
    """
    Generates a random taskset in rt-app's JSON format.

    Args:
        num_tasks (int): The number of tasks to generate.
        period_min_ms (int): The minimum task period in milliseconds.
        period_max_ms (int): The maximum task period in milliseconds.
        period_gran_ms (int): The period granularity in milliseconds.
        max_task_util (float): The maximum utilization for any single task.
        total_utilization (float): The target total utilization for the taskset.
        verbose (bool): Enable verbose output for debugging.

    Returns:
        str: A text string representing the rt-app taskset.
    """

    # Check if the constraint is mathematically possible
    min_required_util = total_utilization / num_tasks
    if min_required_util > max_task_util:
        print(f"Error: Impossible constraint - {num_tasks} tasks with total utilization {total_utilization:.2f}")
        print(f"  Each task must have utilization >= {min_required_util:.3f}, but max_task_util = {max_task_util:.3f}")
        print(f"  Solutions:")
        print(f"    1. Increase max_task_util to at least {min_required_util:.3f}")
        print(f"    2. Decrease the taskset utilization to at most {max_task_util * num_tasks:.2f}")
        print(f"    3. Increase number of tasks")
        return None

    # Generate task utilizations until they meet the max_task_util constraint
    max_attempts = 1000  # Prevent infinite loops
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        task_utils = uunifast(num_tasks, total_utilization)
        if all(u <= max_task_util for u in task_utils):
            if verbose:
                print(f"Generated valid utilizations after {attempts} attempt(s): {[f'{u:.3f}' for u in task_utils]}")
            break
    
    if attempts >= max_attempts:
        print(f"Error: Failed to generate valid utilizations after {max_attempts} attempts")
        print(f"  Consider adjusting parameters:")
        print(f"    - Increase max_task_util (currently {max_task_util:.3f})")
        print(f"    - Decrease the taskset utilization (currently {total_utilization:.3f})")
        print(f"    - Increase number of tasks (currently {num_tasks})")
        return None

    # Generate parameters for each task
    result = ""
    for i in range(num_tasks):
        task_name = f"task_{i}"
        
        # Get the pre-calculated utilization for this task
        utilization = task_utils[i]
        
        # Randomly select a period within the specified range (in microseconds)
        period_us = random.randint(period_min_ms, period_max_ms) * 1000
        
        # Calculate the deadline runtime (dl_runtime) based on utilization and period
        # This represents the maximum time the task can execute within its deadline
        computation_time_us = math.floor(utilization * period_us)

        if verbose:
            print(f"  {task_name}: util={utilization:.3f}, period={period_us} µs, execution_time={computation_time_us} µs")

        result += f"{computation_time_us} {period_us} {period_us}" + "\n"

    # Return the configuration as a formatted JSON string
    return result 

def main():
    """
    Main function to parse command-line arguments and run the generator.
    """
    parser = argparse.ArgumentParser(
        description="Generate a random taskset for rt-app in JSON format.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Arguments for taskset generation
    parser.add_argument("-n", "--tasks", type=int, help="Number of tasks to generate.")
    parser.add_argument("-p", "--period-min", type=int, help="Minimum task period in milliseconds.")
    parser.add_argument("-P", "--period-max", type=int, help="Maximum task period in milliseconds.")
    parser.add_argument("-g", "--period-gran", type=int, help="Period granularity.")
    parser.add_argument("-d", "--period-distribution", type=str, help="Period distrubution ('unif' or 'logunif').")
    parser.add_argument("-S", "--seed", type=int, help="Seed for the pseudo-random numbers generator.")
    parser.add_argument("-u", "--taskset-utilization", type=float, help="Target total utilization for the taskset. Defaults to 70%% of system capacity.")
    parser.add_argument("--max-util", type=float, help="Maximum utilization for a single task (0.0 to 1.0).")
    
    # Arguments for file I/O
    parser.add_argument("-o", "--output", type=str, help="Output JSON file name.")
    parser.add_argument("--config", type=str, help="Path to a JSON configuration file with generator parameters.")
    
    # Debugging options
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output for debugging.")

    args = parser.parse_args()

    # --- Configuration Loading ---
    # Start with an empty config dictionary
    config_params = {}
    
    # Store verbose flag for later use
    verbose = args.verbose

    # Load from config file first, if provided
    if args.config:
        if os.path.exists(args.config):
            with open(args.config, 'r') as f:
                config_params = json.load(f)
            if verbose:
                print(f"Loaded configuration from '{args.config}': {config_params}")
        else:
            print(f"Error: Configuration file not found at '{args.config}'")
            return

    # Override with command-line arguments.
    # An argument is considered provided if it's not None.
    cli_args = {
        'tasks': args.tasks,
        'period_min': args.period_min,
        'period_max': args.period_max,
        'period_gran': args.period_gran,
        'period_distribution': args.period_distribution,
        'seed': args.seed,
        'max_util': args.max_util,
        'taskset_utilization': args.taskset_utilization,
        'output': args.output,
    }
    
    # Filter out None values and update the parameters
    for key, value in cli_args.items():
        if value is not None:
            config_params[key] = value
            if verbose:
                print(f"Override: {key} = {value}")

    # --- Set Defaults and Validate ---
    # Set default values for any parameter that is still missing
    defaults = {
        'period_min': 10,
        'period_max': 100,
        'period_gran': 1,
        'period_distribution': "unif",
        'seed': time.time(),
        'max_util': 0.8,
        'output': None,
    }
    for key, value in defaults.items():
        if key not in config_params:
            config_params[key] = value
            if verbose:
                print(f"Default: {key} = {value}")

    if config_params['period_distribution'] != "unif":
        print(f"Distribution {config_params['period_distribution']} is not supported (yet)")
        sys.exit(-1)

    if config_params['period_gran'] != 1:
        print(f"Period granularity {config_params['period_gran']} is not supported (yet)")
        sys.exit(-1)

    # Required parameters must be present now
    required_params = ['tasks', 'taskset_utilization']
    for param in required_params:
        if param not in config_params:
            print(f"Error: Missing required parameter '{param}'. Provide it via command line or config file.")
            return
            
    if verbose:
        print(f"\nGenerating taskset with parameters:")
        print(f"  Tasks: {config_params['tasks']}")
        print(f"  Period range: {config_params['period_min']}-{config_params['period_max']} ms")
        print(f"  Max task utilization: {config_params['max_util']}")
        print(f"  Total utilization: {config_params['taskset_utilization']}")
        print()

    random.seed(config_params['seed'])
    # --- Generate Taskset ---
    taskset = generate_taskset(
        num_tasks=config_params['tasks'],
        period_min_ms=config_params['period_min'],
        period_max_ms=config_params['period_max'],
        period_gran_ms=config_params['period_gran'],
        max_task_util=config_params['max_util'],
        total_utilization=config_params['taskset_utilization'],
        verbose=verbose
    )

    # Check if generation failed
    if taskset is None:
        print("Taskset generation failed. Exiting.")
        return

    # Write the JSON to the specified output file
    output_file = config_params['output']
    if output_file is None:
        sys.stdout.write(taskset)
    else:
        with open(output_file, 'w') as f:
            f.write(taskset)

    if verbose:
        print(f"Generated taskset JSON:")
        print(taskset)
        print()

    print(f"Successfully generated taskset and saved to '{output_file}'", file=sys.stderr)
    print(f"To run, convert to an rt-app JSON using generate_json.py", file=sys.stderr)

if __name__ == "__main__":
    main()
