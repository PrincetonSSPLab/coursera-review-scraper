#!/usr/bin/env python
# coding: utf-8

# ## Coursera Review Scraper
#
# Sends requests to Coursera and parses out review information using open public API endpoints


import requests
import json
import re
import logging
import time
import os
import queue

from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm


def parse_reviews(api_response):
    """Parse the API response and return a list of reviews.

    Parameters
    ----------
    api_response : dict
        The API response.

    Returns
    -------
    reviews : list
        A list of reviews.
    """
    reviews = []
    for review in api_response[0]["data"]["ProductReviewsV1Resource"]["reviews"]["elements"]:
        reviews.append({
            "id": review["id"],
            "reviewedAt": review["reviewedAt"],
            "rating": review["rating"],
            "isMarkedHelpful": review["isMarkedHelpful"],
            "reviewText": review["reviewText"]["cml"]["value"],
            "productCompleted": review["productCompleted"],
            "mostHelpfulVoteCount": review["mostHelpfulVoteCount"],
            "users": review["users"]["publicDemographics"]["fullName"],
            "user_id": review["users"]["id"]
        })
    return reviews


def create_payload(course_id, no_of_reviews, offset, rating_values=None, product_completed=None, sort_by_helpful_votes=False):
    """Create the payload for the API request.

    Parameters
    ----------
    course_id : str
        The course ID.

    no_of_reviews : int
        The number of reviews to fetch.

    offset : int
        The offset to start fetching reviews from.

    rating_values : list, optional
        The list of rating values to filter reviews by. Default is to not filter.

    product_completed : bool, optional
        Whether to filter reviews by people who completed the course. Default is to not filter.

    sort_by_helpful_votes : bool, optional
        Whether to sort the reviews by helpful votes. Default is to not sort.

    Returns
    -------
    payload : dict
        The payload for the API request.
    """
    if rating_values is None:
        rating_values = [1, 2, 3, 4, 5]
    payload = [
        {
            "operationName": "AllCourseReviews",
            "variables": {
                "courseId": course_id,
                "limit": no_of_reviews,
                "start": f"{offset}",
                "ratingValues": rating_values,
                "productCompleted": product_completed,
                "sortByHelpfulVotes": sort_by_helpful_votes
            },
            "query": "query AllCourseReviews($courseId: String!, $limit: Int!, $start: String!, $ratingValues: [Int!], $productCompleted: Boolean, $sortByHelpfulVotes: Boolean!) {\n  ProductReviewsV1Resource {\n    reviews: byProduct(productId: $courseId, ratingValues: $ratingValues, limit: $limit, start: $start, productCompleted: $productCompleted, sortByHelpfulVotes: $sortByHelpfulVotes) {\n      elements {\n        ...ReviewFragment\n        __typename\n      }\n      paging {\n        total\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment ReviewFragment on ProductReviewsV1 {\n  id\n  reviewedAt\n  rating\n  isMarkedHelpful\n  reviewText {\n    ... on ProductReviewsV1_cmlMember {\n      cml {\n        dtdId\n        value\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  productCompleted\n  mostHelpfulVoteCount\n  users {\n    id\n    publicDemographics {\n      fullName\n      __typename\n    }\n    __typename\n  }\n  __typename\n}\n"
        }]
    return payload


def create_headers():
    """Create the headers for the API request."""
    headers = {
        "authority": "www.coursera.org",
        "accept": "*/*",
        "accept-language": "en",
        "cache-control": "no-cache",
        "content-type": "application/json",
        # # "cookie": "__204u=3366318425-1660148596477; __204r=; CSRF3-Token=1667484412.wNBElFPqBT3OKJ4T; __400v=ff7537ba-faf8-481c-a709-e53affba0225; __400vt=1666895389764; CSRF3-Token=1667759135.Ukq2xJ8MaoD4R3Np; __204u=8221909554-1660726719535",
        "dnt": "1",
        "operation-name": "AllCourseReviews",
        "origin": "https://www.coursera.org",
        "pragma": "no-cache",
        # "r2-app-version": "c508720f55bd0c5242fd129f6f68bfeded0825a0",
        # # "referer": "https://www.coursera.org/learn/python-data/reviews?page=1&sort=recent",
        "sec-ch-ua": '"Chromium";v="106", "Google Chrome";v="106", "Not;A=Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36",
        # "x-coursera-application": "reviews",
        # "x-coursera-version": "c508720f55bd0c5242fd129f6f68bfeded0825a0",
        # # "x-csrf3-token": "1667484412.wNBElFPqBT3OKJ4T"
    }
    return headers


def request_data(url, headers, payload):
    """Make a request to the API and return the response.

    Parameters
    ----------
    url : str
        The URL to make the request to.

    headers : dict
        The headers for the request.

    payload : dict
        The payload for the request.

    Returns
    -------
    response : dict
        The response from the API.
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Making request to {url}")
    logger.debug(f"Headers: {headers}")
    logger.debug(f"Payload: {payload}")
    response = requests.post(url, headers=headers, json=payload)
    logger.debug(f"Request status code: {response.status_code}")
    return response.json()


def get_total_number_reviews_for_rating(course_id, rating_value):
    """Get the total number of reviews for a given rating value.

    Parameters
    ----------
    course_id : str
        The course ID.

    rating_value : int
        The rating value.

    Returns
    -------
    total_number_reviews : int
        The total number of reviews for the given rating value.
    """
    payload = create_payload(course_id, 1, 0, rating_values=[rating_value])
    headers = create_headers()
    response = request_data(reviews_endpoint_url, headers, payload)
    total_number_reviews = response[0]['data']['ProductReviewsV1Resource']['reviews']['paging']['total']
    return total_number_reviews


def safe_request_wrapper(header_payload, allowed_fails=1, delay=1):
    """A wrapper function to make a request to the API.

    Parameters
    ----------
    header_payload : tuple
        A tuple containing the headers and payload for the request.

    allowed_fails : int, optional
        The number of allowed fails before the request is aborted.

    delay : int, optional
        The delay in seconds between each request.

    Returns
    -------
    list
        The list of reviews for the given rating value.
    """
    headers, payload = header_payload
    return safe_request(headers, payload, allowed_fails, delay)


def safe_request(headers, payload, allowed_fails, delay):
    """Make a request to the API and return the response.

    If the request fails, it will retry the request up to allowed_fails times
    with a delay of delay seconds between each retry.

    Parameters
    ----------
    headers : dict
        The headers for the request.

    payload : dict
        The payload for the request.

    allowed_fails : int
        The number of times to retry the request if it fails.

    delay : int
        The number of seconds to wait between each retry.

    Returns
    -------
    reviews : list
        The list of reviews.
    """
    logger = logging.getLogger(__name__)
    fails = 0
    while True:
        try:
            response = request_data(reviews_endpoint_url, headers, payload)
            reviews = parse_reviews(response)
            if not reviews:
                logger.info(
                    f"API failed to return reviews for payload: {payload}.")
                fail_count += 1
                if fail_count > allowed_fails:
                    logger.info(
                        f"API returned no more reviews payload: {payload} for {fails} times. Stopping")
                    return []
                time.sleep(delay)
                continue
            logger.info(
                f"API returned {len(reviews)} reviews for payload: {payload}.")
            return reviews
        except Exception as e:
            logger.info(
                f"API returned an error for payload: {payload}. Error: {e}")
            fail_count += 1
            if fail_count > allowed_fails:
                logger.info(
                    f"API returned an error for payload: {payload} for {fails} times. Stopping")
                return []
            time.sleep(delay)
            continue


def tqdm_threadpool_map(func, iterable, no_threads, iterable_length, *args):
    """A threadpool map function that shows a progress bar.

    Parameters
    ----------
    func : function
        The function to apply to each element of the iterable.

    iterable : iterable
        The iterable to apply the function to.

    no_threads : int
        The number of threads to use.

    iterable_length : int
        The length of the iterable.

    *args : list
        The list of arguments to pass to the function.

    Returns
    -------
    results : list
        The list of results from the function.
    """
    with ThreadPoolExecutor(max_workers=no_threads) as executor:
        results = list(
            tqdm(executor.map(func, iterable, *args), total=iterable_length))
    return results


def get_all_course_reviews_by_rating(course_id, rating, limit=25, start=0, product_completed=None, sort_by_helpful_votes=False):
    """Get all the reviews for a given rating.

    Parameters
    ----------
    course_id : str
        The course ID.

    rating : int
        The rating value.

    limit : int, optional
        The number of reviews to return per request. The default is 25. The maximum is 100.

    start : int, optional
        The number of reviews to skip. The default is 0.

    product_completed : bool, optional
        Whether the product was completed. The default is None. If None, all reviews are returned.

    sort_by_helpful_votes : bool, optional
        Whether to sort the reviews by helpful votes. The default is False.  

    Returns
    -------
    reviews : list
        The list of reviews.
    """
    logger = logging.getLogger(__name__)

    total_reviews_for_rating = get_total_number_reviews_for_rating(
        course_id, rating)
    logger.info(
        f"Total number of reviews for rating {rating}: {total_reviews_for_rating} for course: {course_id}")

    request_payloads = []
    request_headers = []
    # Precompute the payloads and headers for each request
    for start in range(start, total_reviews_for_rating, limit):
        payload = create_payload(course_id, limit, start, rating_values=[
                                 rating], product_completed=product_completed, sort_by_helpful_votes=sort_by_helpful_votes)
        header = create_headers()
        request_payloads.append(payload)
        request_headers.append(header)

    no_threads = 16
    length = len(request_payloads)
    iterable = zip(request_headers, request_payloads)
    logger.info(
        f"Starting {no_threads} threads to get reviews for rating {rating} for course: {course_id} with {length} requests.")
    reviews = tqdm_threadpool_map(
        safe_request_wrapper, iterable, no_threads, length)

    if not reviews:
        logger.info(
            f"No reviews found for rating {rating} for course: {course_id}")
        return []

    flattened_reviews = [
        review for review_list in reviews for review in review_list]
    if len(flattened_reviews) != total_reviews_for_rating:
        logger.info(
            f"Number of reviews returned for rating {rating} for course: {course_id} does not match the total number of reviews. Expected: {total_reviews_for_rating} Actual: {len(flattened_reviews)}")

    return flattened_reviews


def get_all_course_reviews(course_id, limit=25, start=0, rating_values=None, product_completed=None, sort_by_helpful_votes=False):
    """Get all course reviews for a given course.

    Parameters
    ----------
    course_id : str
        The course ID.

    limit : int, optional
        The number of reviews to return per request. The default is 25.

    start : int, optional
        The index of the first review to return. The default is 0.

    rating_values : list, optional
        The list of rating values to filter by. The default is [1, 2, 3, 4, 5].

    product_completed : bool, optional
        Whether to filter by product completed. The default is None.

    sort_by_helpful_votes : bool, optional
        Whether to sort by helpful votes. The default is False.

    Returns
    -------
    reviews : list
        A list of reviews.
    """
    if rating_values is None:
        rating_values = [1, 2, 3, 4, 5]

    all_reviews = []
    for rating in rating_values:
        reviews_for_rating = get_all_course_reviews_by_rating(
            course_id, rating, limit, start, product_completed, sort_by_helpful_votes)
        all_reviews.extend(reviews_for_rating)

    logger.info(
        f"Total number of reviews scraped for course: {course_id} is {len(all_reviews)}")
    return all_reviews


def create_logger():
    """Creates a logger. 

    Creates a logger that generates a logging information.

    Returns
    -------
    logger : logger
        The logger.
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    output_log_file_name = f"{'coursera-reviews'}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    file_path = os.path.join(os.getcwd(), "logs", output_log_file_name)
    fh = logging.FileHandler(file_path)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    return logger


if __name__ == "__main__":
    reviews_endpoint_url = "https://www.coursera.org/graphqlBatch?opname=AllCourseReviews"
    logger = create_logger()

    reviews = get_all_course_reviews(
        "COURSE~P--h6zpNEeWYbg7p2_3OHQ", rating_values=[1, 2, 3, 4, 5])

    review_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for review in reviews:
        review_counts[review["rating"]] += 1

    unique_people = set()
    for review in reviews:
        unique_people.add(review["user_id"])

    print(len(unique_people))
    print(review_counts)
